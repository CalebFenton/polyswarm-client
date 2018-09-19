import asyncio
import logging
import functools

from polyswarmclient import Client
from polyswarmclient.events import RevealAssertion, SettleBounty


class Microengine(object):
    def __init__(self, client, testing=0, scanner=None, chains={'home'}):
        self.client = client
        self.chains = chains
        self.scanner = scanner
        self.client.on_new_bounty.register(functools.partial(Microengine.handle_new_bounty, self))
        self.client.on_reveal_assertion_due.register(functools.partial(Microengine.handle_reveal_assertion, self))
        self.client.on_settle_bounty_due.register(functools.partial(Microengine.handle_settle_bounty, self))

        self.testing = testing
        self.bounties_seen = 0
        self.reveals_posted = 0
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
            return await self.scanner.scan(guid, content, chain)

        return False, False, ''

    def bid(self, guid, chain):
        """Override this to implement custom bid calculation logic

        Args:
            guid (str): GUID of the bounty under analysis, use to correlate with artifacts in the same bounty
            chain (str): Chain we are operating on
        Returns:
            (int): Amount of NCT to bid in base NCT units (10 ^ -18)
        """
        return self.client.bounties.parameters[chain]['assertion_bid_minimum']

    def run(self):
        self.client.run(self.chains)

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
        if self.testing > 0:
            if self.bounties_seen > self.testing:
                logging.warning('Received new bounty, but finished with testing mode')
                return []
            logging.info('Testing mode, %s bounties remaining', self.testing - self.bounties_seen)

        mask = []
        verdicts = []
        metadatas = []
        async for content in self.client.get_artifacts(uri):
            bit, verdict, metadata = await self.scan(guid, content, chain)
            mask.append(bit)
            verdicts.append(verdict)
            metadatas.append(metadata)

        if not any(mask):
            return []

        expiration = int(expiration)
        assertion_reveal_window = self.client.bounties.parameters[chain]['assertion_reveal_window']
        arbiter_vote_window = self.client.bounties.parameters[chain]['arbiter_vote_window']
        
        logging.info('Responding to bounty: %s', guid)
        nonce, assertions = await self.client.bounties.post_assertion(guid, self.bid(guid, chain), mask, verdicts, chain)
        for a in assertions:
            ra = RevealAssertion(guid, a['index'], nonce, verdicts, ';'.join(metadatas))
            self.client.schedule(expiration, ra, chain)

            sb = SettleBounty(guid)
            self.client.schedule(expiration + assertion_reveal_window + arbiter_vote_window, sb, chain)

        return assertions

    async def handle_reveal_assertion(self, bounty_guid, index, nonce, verdicts, metadata, chain):
        self.reveals_posted += 1
        if self.testing > 0:
            if self.reveals_posted > self.testing:
                logging.warning('Scheduled reveal, but finished with testing mode')
                return []
            logging.info('Testing mode, %s reveals remaining', self.testing - self.reveals_posted)
        return await self.client.bounties.post_reveal(bounty_guid, index, nonce, verdicts, metadata, chain)

    async def handle_settle_bounty(self, bounty_guid, chain):
        self.settles_posted += 1
        if self.testing > 0:
            if self.settles_posted > self.testing:
                logging.warning('Scheduled settle, but finished with testing mode')
                return []
            logging.info('Testing mode, %s settles remaining', self.testing - self.settles_posted)

        ret = await self.client.bounties.settle_bounty(bounty_guid, chain)
        if self.testing > 0 and self.settles_posted >= self.testing:
            logging.info("All testing bounties complete, exiting")
            self.client.stop()
        return ret
