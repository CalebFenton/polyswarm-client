import asyncio
import logging

from polyswarmclient import Client
from polyswarmclient.events import VoteOnBounty, SettleBounty


class Arbiter(object):
    def __init__(self, client, testing=0, scanner=None, chains={'home'}):
        self.client = client
        self.chains = chains
        self.scanner = scanner
        self.client.on_run.register(self.handle_run)
        self.client.on_new_bounty.register(self.handle_new_bounty)
        self.client.on_vote_on_bounty_due.register(self.handle_vote_on_bounty)
        self.client.on_settle_bounty_due.register(self.handle_settle_bounty)

        self.testing = testing
        self.bounties_seen = 0
        self.votes_posted = 0
        self.settles_posted = 0

    @classmethod
    def connect(cls, polyswarmd_addr, keyfile, password, api_key=None, testing=0, insecure_transport=False, scanner=None, chains={'home'}):
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

            bit (bool): Whether to include this artifact in the assertion or not
            verdict (bool): Whether this artifact is malicious or not
            metadata (str): Optional metadata about this artifact
        """
        if self.scanner:
            return await self.scacnner.scan(guid, content, chain)

        return False, False, ''

    def run(self):
        self.client.run(self.chains)

    async def handle_run(self, chain):
        min_stake = self.client.staking.parameters[chain]['minimum_stake']
        balance = await self.client.staking.get_total_balance(chain)
        if balance < min_stake:
            deposits = await self.client.staking.post_deposit(min_stake - balance, chain)
            logging.info('Depositing stake: %s', deposits)

    async def handle_new_bounty(self, guid, author, amount, uri, expiration, chain):
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
                logging.info('Received new bounty, but finished with testing mode')
                return []
            logging.info('Testing mode, %s bounties remaining', self.testing - self.bounties_seen)

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

    async def handle_vote_on_bounty(self, bounty_guid, verdicts, valid_bloom, chain):
        self.votes_posted += 1
        if self.testing:
            if self.votes_posted > self.testing:
                logging.warning('Scheduled vote, but finished with testing mode')
                return []
            logging.info('Testing mode, %s votes remaining', self.testing - self.votes_posted)
        return await self.client.bounties.post_vote(bounty_guid, verdicts, valid_bloom, chain)

    async def handle_settle_bounty(self, bounty_guid, chain):
        self.settles_posted += 1
        if self.testing:
            if self.settles_posted > self.testing:
                logging.warning('Scheduled settle, but finished with testing mode')
                return []
            logging.info('Testing mode, %s settles remaining', self.testing - self.settles_posted)

        ret = await self.client.bounties.settle_bounty(bounty_guid, chain)
        if self.testing and self.settles_posted >= self.testing:
            logging.info("All testing bounties complete, exiting")
            self.client.stop()
        return ret
