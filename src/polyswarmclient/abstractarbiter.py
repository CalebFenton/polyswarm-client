import asyncio
import logging

from polyswarmclient import Client
from polyswarmclient.events import VoteOnBounty, SettleBounty
from polyswarmclient.utils import asyncio_stop

logger = logging.getLogger(__name__)  # Initialize logger
MAX_STAKE_RETRIES = 10


class AbstractArbiter():

    def __init__(self, client, testing=0, scanner=None, chains=None):
        self.client = client
        self.chains = chains
        self.scanner = scanner
        self.client.on_run.register(self.__handle_run)
        self.client.on_new_bounty.register(self.__handle_new_bounty)
        self.client.on_vote_on_bounty_due.register(self.__handle_vote_on_bounty)
        self.client.on_settle_bounty_due.register(self.__handle_settle_bounty)

        self.testing = testing
        self.bounties_pending = {}
        self.bounties_pending_locks = {}
        self.bounties_seen = 0
        self.votes_posted = 0
        self.settles_posted = 0

    @classmethod
    def connect(cls, polyswarmd_addr, keyfile, password, api_key=None, testing=0, insecure_transport=False,
                scanner=None, chains=None):
        """Connect the Arbiter to a Client.

        Args:
            polyswarmd_addr (str): URL of polyswarmd you are referring to.
            keyfile (str): Keyfile filename.
            password (str): Password associated with Keyfile.
            api_key (str): Your PolySwarm API key.
            testing (int): Number of testing bounties to use.
            insecure_transport (bool): Allow insecure transport such as HTTP?
            chains (set(str)):  Set of chains you are acting on.

        Returns:
            AbstractArbiter: Arbiter instantiated with a Client.
        """
        client = Client(polyswarmd_addr, keyfile, password, api_key, testing > 0, insecure_transport)
        return cls(client, testing, scanner, chains)

    async def scan(self, guid, content, chain):
        """Override this to implement custom scanning logic

        Args:
            guid (str): GUID of the bounty under analysis, use to track artifacts in the same bounty
            content (bytes): Content of the artifact to be scan
            chain (str): Chain we are operating on
        Returns:
            ScanResult: Result of this scan
        """
        if self.scanner:
            return await self.scanner.scan(guid, content, chain)

        raise NotImplementedError("You must subclass this class and override this method.")

    def run(self):
        """
        Run the Client on the Arbiter's chains.
        """
        self.client.run(self.chains)

    async def __handle_run(self, chain):
        """
        If the Client's current balance is less than the minimum stake
        then deposit the difference between the two to the given chain.

        Args:
            chain (str): Chain we are operating on.
        """
        self.bounties_pending_locks[chain] = asyncio.Lock()

        min_stake = await self.client.staking.parameters[chain].get('minimum_stake')
        staking_balance = await self.client.staking.get_total_balance(chain)
        tries = 0
        if staking_balance < min_stake:
            while True:
                nct_balance = await self.client.balances.get_nct_balance(chain)
                if self.testing > 0 and nct_balance < min_stake - staking_balance and tries >= MAX_STAKE_RETRIES:
                    logger.error('Failed %d attempts to deposit due to low balance. Exiting', tries)
                    self.client.exit_code = 1
                    asyncio_stop()
                elif nct_balance < min_stake - staking_balance:
                    logger.warning('Insufficient balance to deposit stake on %s. Have %s NCT. Need %s NCT', chain,
                                   nct_balance, min_stake - staking_balance)
                    tries += 1
                    await asyncio.sleep(tries * tries)
                    continue

                deposits = await self.client.staking.post_deposit(min_stake - staking_balance, chain)
                logger.info('Depositing stake: %s', deposits)
                break

    async def __handle_new_bounty(self, guid, author, amount, uri, expiration, block_number, txhash, chain):
        """Scan and assert on a posted bounty

        Args:
            guid (str): The bounty to assert on
            author (str): The bounty author
            amount (str): Amount of the bounty in base NCT units (10 ^ -18)
            uri (str): IPFS hash of the root artifact
            expiration (str): Block number of the bounty's expiration
            block_number (int): Block number the bounty was posted on
            txhash (str): Transaction hash which caused the event
            chain (str): Is this on the home or side chain?
        Returns:
            Response JSON parsed from polyswarmd containing placed assertions
        """
        async with self.bounties_pending_locks[chain]:
            bounties_pending = self.bounties_pending.get(chain, set())
            if guid in bounties_pending:
                logger.info('Bounty %s already seen, not responding', guid)
                return []
            self.bounties_pending[chain] = bounties_pending | {guid}

        self.bounties_seen += 1
        if self.testing > 0:
            if self.bounties_seen > self.testing:
                logger.info('Received new bounty, but finished with testing mode')
                return []
            logger.info('Testing mode, %s bounties remaining', self.testing - self.bounties_seen)

        votes = []
        async for content in self.client.get_artifacts(uri):
            result = await self.scan(guid, content, chain)
            votes.append(result.verdict)

        bounty = await self.client.bounties.get_bounty(guid, chain)
        if bounty is None:
            logger.error('Unable to get retrieve new bounty')
            return []

        bloom_parts = await self.client.bounties.get_bloom(guid, chain)
        bounty_bloom = 0
        for b in bloom_parts:
            bounty_bloom = bounty_bloom << 256 | int(b)

        calculated_bloom = await self.client.bounties.calculate_bloom(uri)
        valid_bloom = bounty and bounty_bloom == calculated_bloom

        expiration = int(expiration)
        assertion_reveal_window = await self.client.bounties.parameters[chain].get('assertion_reveal_window')
        arbiter_vote_window = await self.client.bounties.parameters[chain].get('arbiter_vote_window')

        vb = VoteOnBounty(guid, votes, valid_bloom)
        self.client.schedule(expiration + assertion_reveal_window, vb, chain)

        sb = SettleBounty(guid)
        self.client.schedule(expiration + assertion_reveal_window + arbiter_vote_window, sb, chain)

        return []

    async def __handle_vote_on_bounty(self, bounty_guid, votes, valid_bloom, chain):
        """
        Submit votes on a given bounty GUID to a given chain.

        Args:
            bounty_guid (str): The bounty which we are voting on.
            votes (List[bool]): Vote (malicious/benign) for each of the artifacts in the bounty.
            valid_bloom (bool):  Is the bloom filter reported by the bounty poster valid?
            chain (str): Which chain to operate on.
        Returns:
            Response JSON parsed from polyswarmd containing emitted events.
        """
        self.votes_posted += 1
        if self.testing > 0:
            if self.votes_posted > self.testing:
                logger.warning('Scheduled vote, but finished with testing mode')
                return []
            logger.info('Testing mode, %s votes remaining', self.testing - self.votes_posted)
        return await self.client.bounties.post_vote(bounty_guid, votes, valid_bloom, chain)

    async def __handle_settle_bounty(self, bounty_guid, chain):
        """
        Settle the given bounty on the given chain.

        Args:
            bounty_guid (str): The bounty which we are settling.
            chain (str): Which chain to operate on.
        Returns:
            Response JSON parsed from polyswarmd containing emitted events.
        """
        async with self.bounties_pending_locks[chain]:
            bounties_pending = self.bounties_pending.get(chain, set())
            if bounty_guid not in bounties_pending:
                logger.info('Bounty %s already settled', bounty_guid)
                return []
            self.bounties_pending[chain] = bounties_pending - {bounty_guid}

        self.settles_posted += 1
        if self.testing > 0:
            if self.settles_posted > self.testing:
                logger.warning('Scheduled settle, but finished with testing mode')
                return []
            logger.info('Testing mode, %s settles remaining', self.testing - self.settles_posted)

        ret = await self.client.bounties.settle_bounty(bounty_guid, chain)
        if self.testing > 0 and self.settles_posted >= self.testing:
            logger.info("All testing bounties complete, exiting")
            asyncio_stop()
        return ret
