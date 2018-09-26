import asyncio
import logging
import sys

from polyswarmclient import Client
from polyswarmclient.events import SettleBounty


class Ambassador(object):
    def __init__(self, client, testing=0, chains={'home'}):
        self.client = client
        self.chains = chains
        self.client.on_run.register(self.handle_run)
        self.client.on_settle_bounty_due.register(self.handle_settle_bounty)

        self.testing = testing
        self.bounties_posted = 0
        self.settles_posted = 0

    @classmethod
    def connect(cls, polyswarmd_addr, keyfile, password, api_key=None, testing=0, insecure_transport=False, chains={'home'}):
        client = Client(polyswarmd_addr, keyfile, password, api_key, testing > 0, insecure_transport)
        return cls(client, testing, chains)

    async def next_bounty(self, chain):
        """Override this to implement different bounty submission queues

        Args:
            chain (str): Chain we are operating on
        Returns:
            (int, str, int): Tuple of amount, ipfs_uri, duration, None to terminate submission

            amount (int): Amount to place this bounty for
            ipfs_uri (str): IPFS URI of the artifact to post
            duration (int): Duration of the bounty in blocks
        """
        return None

    def on_bounty_posted(self, guid, amount, ipfs_uri, expiration, chain):
        """Override this to implement additional steps after bounty submission

        Args:
            guid (str): GUID of the posted bounty
            amount (int): Amount of the posted bounty
            ipfs_uri (str): URI of the artifact submitted
            expiration (int): Block number of bounty expiration
            chain (str): Chain we are operating on
        """
        pass

    def run(self):
        self.client.run(self.chains)

    async def handle_run(self, chain):
        asyncio.get_event_loop().create_task(self.run_task(chain))

    async def run_task(self, chain):
        assertion_reveal_window = self.client.bounties.parameters[chain]['assertion_reveal_window']
        arbiter_vote_window = self.client.bounties.parameters[chain]['arbiter_vote_window']

        # HACK: In testing mode we start up ambassador/arbiter/microengine
        # immediately and start submitting bounties, however arbiter has to wait
        # a block for its staking tx to be mined before it starts respoonding.
        # Add in a sleep for now, this will be addressed properly in
        # polyswarm-client#5
        if self.testing > 0:
            logging.info('Waiting for arbiter and microengine')
            await asyncio.sleep(5)

        bounty = await self.next_bounty(chain)
        while bounty is not None:
            # Exit if we are in testing mode
            if self.testing > 0 and self.bounties_posted >= self.testing:
                logging.info('All testing bounties submitted')
                break
            self.bounties_posted += 1

            logging.info('Submitting bounty %s: %s', self.bounties_posted, bounty)
            amount, ipfs_uri, duration = bounty
            bounties = await self.client.bounties.post_bounty(amount, ipfs_uri, duration, chain)

            for b in bounties:
                guid = b['guid']
                expiration = int(b['expiration'])

                # Handle any additional steps in derived implementations
                self.on_bounty_posted(guid, amount, ipfs_uri, expiration, chain)

                sb = SettleBounty(guid)
                self.client.schedule(expiration + assertion_reveal_window + arbiter_vote_window, sb, chain)

            bounty = await self.next_bounty(chain)

    async def handle_settle_bounty(self, bounty_guid, chain):
        self.settles_posted += 1
        if self.testing > 0:
            if self.settles_posted > self.testing:
                logging.warning('Scheduled settle, but finished with testing mode')
                return []
            logging.info('Testing mode, %s settles remaining', self.testing - self.settles_posted)

        ret = await self.client.bounties.settle_bounty(bounty_guid, chain)
        if self.testing > 0 and self.settles_posted == self.testing:
            logging.info("All testing bounties complete, exiting")
            self.client.stop()
        return ret
