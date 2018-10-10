import asyncio
import logging

from polyswarmclient import Client
from polyswarmclient.events import VoteOnBounty, SettleBounty

logger = logging.getLogger(__name__)


class Arbiter(object):
    def __init__(self, client, testing=0, scanner=None, chains={'home'}):
        self.client = client
        self.chains = chains
        self.scanner = scanner
        self.client.on_run.register(self.__handle_run)
        self.client.on_new_bounty.register(self.__handle_new_bounty)
        self.client.on_vote_on_bounty_due.register(self.__handle_vote_on_bounty)
        self.client.on_settle_bounty_due.register(self.__handle_settle_bounty)

        self.testing = testing
        self.bounties_seen = 0
        self.votes_posted = 0
        self.settles_posted = 0

    @classmethod
    def connect(cls, polyswarmd_addr, keyfile, password, api_key=None, testing=0, insecure_transport=False, scanner=None, chains={'home'}):
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
            Arbiter: Arbiter instantiated with a Client.
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
            (bool, bool, str): Tuple of bit, verdict, metadata

        Note:
            | The meaning of the return types are as follows:
            |   - **bit** (*bool*): Whether to include this artifact in the assertion or not
            |   - **verdict** (*bool*): Whether this artifact is malicious or not
            |   - **metadata** (*str*): Optional metadata about this artifact
        """
        if self.scanner:
            return await self.scacnner.scan(guid, content, chain)

        return False, False, ''

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
        min_stake = self.client.staking.parameters[chain]['minimum_stake']
        balance = await self.client.staking.get_total_balance(chain)
        if balance < min_stake:
            deposits = await self.client.staking.post_deposit(min_stake - balance, chain)
            logger.info('Depositing stake: %s', deposits)

    async def __handle_new_bounty(self, guid, author, amount, uri, expiration, chain):
        """Scan and assert on a posted bounty

        Args:
            guid (str): The bounty to assert on
            author (str): The bounty author
            amount (str): Amount of the bounty in base NCT units (10 ^ -18)
            uri (str): IPFS hash of the root artifact
            expiration (str): Block number of the bounty's expiration
            chain (str): Is this on the home or side chain?

        Returns:
            Response JSON parsed from polyswarmd containing placed assertions
        """
        self.bounties_seen += 1
        if self.testing:
            if self.bounties_seen > self.testing:
                logger.info('Received new bounty, but finished with testing mode')
                return []
            logger.info('Testing mode, %s bounties remaining', self.testing - self.bounties_seen)

        verdicts = []
        async for content in self.client.get_artifacts(uri):
            bit, verdict, metadata = await self.scan(guid, content, chain)
            verdicts.append(verdict)

        bounty = await self.client.bounties.get_bounty(guid, chain)
        bloom = await self.client.bounties.calculate_bloom(uri)
        valid_bloom = bounty and int(bounty.get('bloom', 0)) == bloom

        expiration = int(expiration)
        assertion_reveal_window = self.client.bounties.parameters[chain]['assertion_reveal_window']
        arbiter_vote_window = self.client.bounties.parameters[chain]['arbiter_vote_window']

        vb = VoteOnBounty(guid, verdicts, valid_bloom)
        self.client.schedule(expiration + assertion_reveal_window, vb, chain)

        sb = SettleBounty(guid)
        self.client.schedule(expiration + assertion_reveal_window + arbiter_vote_window, sb, chain)

        return []

    async def __handle_vote_on_bounty(self, bounty_guid, verdicts, valid_bloom, chain):
        """
        Submit verdicts on a given bounty GUID to a given chain.

        Args:
            bounty_guid (str): The bounty which we are voting on.
            verdicts (List[bool]): Verdict (malicious/benign) for each of the artifacts in the bounty.
            valid_bloom (bool):  Is the bloom filter reported by the bounty poster valid?
            chain (str): Which chain to operate on.
        Returns:
            Response JSON parsed from polyswarmd containing emitted events.
        """
        self.votes_posted += 1
        if self.testing:
            if self.votes_posted > self.testing:
                logger.warning('Scheduled vote, but finished with testing mode')
                return []
            logger.info('Testing mode, %s votes remaining', self.testing - self.votes_posted)
        return await self.client.bounties.post_vote(bounty_guid, verdicts, valid_bloom, chain)

    async def __handle_settle_bounty(self, bounty_guid, chain):
        """
        Settle the given bounty on the given chain.

        Args:
            bounty_guid (str): The bounty which we are settling.
            chain (str): Which chain to operate on.
        Returns:
            Response JSON parsed from polyswarmd containing emitted events.
        """
        self.settles_posted += 1
        if self.testing:
            if self.settles_posted > self.testing:
                logger.warning('Scheduled settle, but finished with testing mode')
                return []
            logger.info('Testing mode, %s settles remaining', self.testing - self.settles_posted)

        ret = await self.client.bounties.settle_bounty(bounty_guid, chain)
        if self.testing > 0 and self.settles_posted >= self.testing:
            logger.info("All testing bounties complete, exiting")
            self.client.stop()
        return ret
