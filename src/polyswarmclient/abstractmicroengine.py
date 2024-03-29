import asyncio
import json
import logging

from polyswarmartifact import ArtifactType
from polyswarmartifact.schema import verdict, Bounty

from polyswarmclient import Client
from polyswarmclient.abstractscanner import ScanResult
from polyswarmclient.bountyfilter import BountyFilter
from polyswarmclient.events import RevealAssertion, SettleBounty
from polyswarmclient.utils import asyncio_stop

logger = logging.getLogger(__name__)


class AbstractMicroengine(object):
    def __init__(self, client, testing=0, scanner=None, chains=None, artifact_types=None, bid_strategy=None,
                 accept=None, exclude=None):
        self.client = client
        self.chains = chains
        self.scanner = scanner
        if artifact_types is None:
            self.valid_artifact_types = [ArtifactType.FILE]
        else:
            self.valid_artifact_types = artifact_types

        self.bounty_filter = BountyFilter(accept, exclude)

        self.client.on_run.register(self.__handle_run)
        self.client.on_new_bounty.register(self.__handle_new_bounty)
        self.client.on_reveal_assertion_due.register(self.__handle_reveal_assertion)
        self.client.on_quorum_reached.register(self.__handle_quorum_reached)
        self.client.on_settled_bounty.register(self.__handle_settled_bounty)
        self.client.on_settle_bounty_due.register(self.__handle_settle_bounty)

        self.bid_strategy = bid_strategy

        self.testing = testing
        self.bounties_pending = {}
        self.bounties_pending_locks = {}
        self.bounties_seen = 0
        self.reveals_posted = 0
        self.settles_posted = 0

    @classmethod
    def connect(cls, polyswarmd_addr, keyfile, password, api_key=None, testing=0, insecure_transport=False,
                scanner=None, chains=None, artifact_types=None, bid_strategy=None, accept=None, exclude=None):
        """Connect the Microengine to a Client.

        Args:
            polyswarmd_addr (str): URL of polyswarmd you are referring to.
            keyfile (str): Keyfile filename.
            password (str): Password associated with Keyfile.
            api_key (str): Your PolySwarm API key.
            testing (int): Number of testing bounties to use.
            insecure_transport (bool): Allow insecure transport such as HTTP?
            scanner (Scanner): `Scanner` instance to use.
            chains (set(str)):  Set of chains you are acting on.
            artifact_types (list(ArtifactType)): List of artifact types you support
            bid_strategy (BidStrategyBase): Bid Strategy for bounties
            accept (list[tuple[str]]): List of accepted mimetypes
            exclude (list[tuple[str]]): List of excluded mimetypes

        Returns:
            AbstractMicroengine: Microengine instantiated with a Client.
        """
        client = Client(polyswarmd_addr, keyfile, password, api_key, testing > 0, insecure_transport)
        return cls(client, testing, scanner, chains, artifact_types, bid_strategy=bid_strategy,
                   accept=accept, exclude=exclude)

    async def scan(self, guid, artifact_type, content, metadata, chain):
        """Override this to implement custom scanning logic

        Args:
            guid (str): GUID of the bounty under analysis, use to track artifacts in the same bounty
            artifact_type (ArtifactType): Artifact type for the bounty being scanned
            content (bytes): Content of the artifact to be scan
            metadata (dict): Metadata about the artifact being scanned
            chain (str): Chain we are operating on
        Returns:
            ScanResult: Result of this scan
        """
        if self.scanner:
            return await self.scanner.scan(guid, artifact_type, content, metadata, chain)

        raise NotImplementedError(
            "You must 1) override this scan method OR 2) provide a scanner to your Microengine constructor")

    async def bid(self, guid, mask, verdicts, confidences, metadatas, chain):
        """Override this to implement custom bid calculation logic

        Args:
            guid (str): GUID of the bounty under analysis
            mask (list[bool]): mask for the from scanning the bounty files
            verdicts (list[bool]): scan verdicts from scanning the bounty files
            confidences (list[float]): Measure of confidence of verdict per artifact ranging from 0.0 to 1.0
            metadatas (list[str]): metadata blurbs from scanning the bounty files
            chain (str): Chain we are operating on

        Returns:
            int: Amount of NCT to bid in base NCT units (10 ^ -18)
        """
        min_allowed_bid = await self.client.bounties.parameters[chain].get('assertion_bid_minimum')
        if self.bid_strategy is not None:
            return max(
                min_allowed_bid,
                await self.bid_strategy.bid(guid, mask, verdicts, confidences, metadatas, min_allowed_bid, chain)
            )

        raise NotImplementedError(
            "You must 1) override this bid method OR 2) provide a bid_strategy to your Microengine constructor")

    async def fetch_and_scan_all(self, guid, artifact_type, uri, duration, metadata, chain):
        """Fetch and scan all artifacts concurrently

        Args:
            guid (str): GUID of the associated bounty
            artifact_type (ArtifactType): Artifact type for the bounty being scanned
            uri (str):  Base artifact URI
            duration (int): Max number of blocks to take
            metadata (list[dict]) List of metadata json blobs for artifacts
            chain (str): Chain we are operating on

        Returns:
            (list(bool), list(bool), list(str)): Tuple of mask bits, verdicts, and metadatas
        """
        async def fetch_and_scan(artifact_metadata, index):
            content = await self.client.get_artifact(uri, index)
            if not self.bounty_filter.is_allowed(artifact_metadata):
                return ScanResult()

            if content is not None:
                return await self.scan(guid, artifact_type, content, artifact_metadata, chain)

            return ScanResult()

        artifacts = await self.client.list_artifacts(uri)
        metadata = BountyFilter.pad_metadata(metadata, len(artifacts))

        return await asyncio.gather(*[
            fetch_and_scan(metadata[i], i) for i in range(len(artifacts))
        ])

    def run(self):
        """
        Run the `Client` on the Microengine's chains.
        """
        self.client.run(self.chains)

    async def __handle_run(self, chain):
        """Perform setup required once on correct loop

        Args:
            chain (str): Chain we are operating on.
        """
        self.bounties_pending_locks[chain] = asyncio.Lock()
        if self.scanner is not None and not await self.scanner.setup():
            logger.critical('Scanner instance reported unsuccessful setup. Exiting.')
            exit(1)

    async def __handle_new_bounty(self, guid, artifact_type, author, amount, uri, expiration, metadata, block_number, txhash, chain):
        """Scan and assert on a posted bounty

        Args:
            guid (str): The bounty to assert on
            artifact_type (ArtifactType): The type of artifacts in this bounty
            author (str): The bounty author
            amount (str): Amount of the bounty in base NCT units (10 ^ -18)
            uri (str): IPFS hash of the root artifact
            expiration (str): Block number of the bounty's expiration
            metadata (dict): Dictionary of metadata or None
            block_number (int): Block number the bounty was placed on
            txhash (str): Transaction hash which caused the event
            chain (str): Is this on the home or side chain?

        Returns:
            Response JSON parsed from polyswarmd containing placed assertions
        """
        # Skip bounties for types we don't support
        if artifact_type not in self.valid_artifact_types:
            logger.info('Bounty artifact type %s is not supported', artifact_type)
            return []

        async with self.bounties_pending_locks[chain]:
            bounties_pending = self.bounties_pending.get(chain, set())
            if guid in bounties_pending:
                logger.debug(f'Bounty {guid} already seen, not responding')
                return []
            self.bounties_pending[chain] = bounties_pending | {guid}

        self.bounties_seen += 1
        if self.testing > 0:
            if self.bounties_seen > self.testing:
                logger.warning('Received new bounty, but finished with testing mode')
                return []
            logger.info(f'Testing mode, {self.testing - self.bounties_seen} bounties remaining')

        expiration = int(expiration)
        duration = expiration - block_number

        results = await self.fetch_and_scan_all(guid, artifact_type, uri, duration, metadata, chain)
        mask = [r.bit for r in results]
        verdicts = [r.verdict for r in results]
        confidences = [r.confidence for r in results]
        metadatas = [r.metadata for r in results]
        combined_metadata = ';'.join(metadatas)

        try:
            if all([metadata and verdict.Verdict.validate(json.loads(metadata)) for metadata in metadatas]):
                combined_metadata = json.dumps([json.loads(metadata) for metadata in metadatas])
        except json.JSONDecodeError:
            logger.exception(f'Error decoding assertion metadata {metadatas}')

        if not any(mask):
            return []

        assertion_fee = await self.client.bounties.parameters[chain].get('assertion_fee')
        assertion_reveal_window = await self.client.bounties.parameters[chain].get('assertion_reveal_window')
        arbiter_vote_window = await self.client.bounties.parameters[chain].get('arbiter_vote_window')

        # Check that microengine has sufficient balance to handle the assertion
        bid = await self.bid(guid, mask, verdicts, confidences, metadatas, chain)
        balance = await self.client.balances.get_nct_balance(chain)
        if balance < assertion_fee + bid:
            logger.critical(f'Insufficient balance to post assertion for bounty on {chain}. Have {balance} NCT. '
                            f'Need {assertion_fee + bid} NCT', extra={'extra': guid})
            if self.testing > 0:
                exit(1)

            return []

        logger.info(f'Responding to {artifact_type.name.lower()} bounty {guid}')
        nonce, assertions = await self.client.bounties.post_assertion(guid, bid, mask, verdicts, chain)
        for a in assertions:
            # Post metadata to IPFS and post ipfs_hash as metadata, if it exists
            ipfs_hash = await self.client.bounties.post_metadata(combined_metadata, chain)
            metadata = ipfs_hash if ipfs_hash is not None else combined_metadata
            ra = RevealAssertion(guid, a['index'], nonce, verdicts, metadata)
            self.client.schedule(expiration, ra, chain)

            sb = SettleBounty(guid)
            self.client.schedule(expiration + assertion_reveal_window + arbiter_vote_window, sb, chain)

        return assertions

    async def __handle_reveal_assertion(self, bounty_guid, index, nonce, verdicts, metadata, chain):
        """
        Callback registered in `__init__` to handle the reveal assertion.

        Args:
            bounty_guid (str): GUID of the bounty being asserted on
            index (int): Index of the assertion to reveal
            nonce (str): Secret nonce used to reveal assertion
            verdicts (List[bool]): List of verdicts for each artifact in the bounty
            metadata (str): Optional metadata
            chain (str): Chain to operate on
        Returns:
            Response JSON parsed from polyswarmd containing emitted events
        """
        self.reveals_posted += 1
        if self.testing > 0:
            if self.reveals_posted > self.testing:
                logger.warning('Scheduled reveal, but finished with testing mode')
                return []
            logger.info(f'Testing mode, {self.testing - self.reveals_posted} reveals remaining')
        return await self.client.bounties.post_reveal(bounty_guid, index, nonce, verdicts, metadata, chain)

    async def __do_handle_settle_bounty(self, bounty_guid, chain):
        """
        Callback registered in `__init__` to handle a settled bounty.

        Args:
            bounty_guid (str): GUID of the bounty being asserted on
            chain (str): Chain to operate on
        Returns:
            Response JSON parsed from polyswarmd containing emitted events
        """
        async with self.bounties_pending_locks[chain]:
            bounties_pending = self.bounties_pending.get(chain, set())
            if bounty_guid not in bounties_pending:
                logger.debug(f'Bounty {bounty_guid} already settled')
                return []
            self.bounties_pending[chain] = bounties_pending - {bounty_guid}

        self.settles_posted += 1
        if self.testing > 0:
            if self.settles_posted > self.testing:
                logger.warning('Scheduled settle, but finished with testing mode')
                return []
            logger.info(f'Testing mode, {self.testing - self.settles_posted} settles remaining')

        ret = await self.client.bounties.settle_bounty(bounty_guid, chain)
        if 0 < self.testing <= self.settles_posted:
            logger.info("All testing bounties complete, exiting")
            asyncio_stop()
        return ret

    async def __handle_quorum_reached(self, bounty_guid, block_number, txhash, chain):
        return await self.__do_handle_settle_bounty(bounty_guid, chain)

    async def __handle_settle_bounty(self, bounty_guid, chain):
        return await self.__do_handle_settle_bounty(bounty_guid, chain)

    async def __handle_settled_bounty(self, bounty_guid, settler, payout, block_number, txhash, chain):
        return await self.__do_handle_settle_bounty(bounty_guid, chain)
