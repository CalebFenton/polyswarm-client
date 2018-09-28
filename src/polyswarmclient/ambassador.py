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
        self.offers_sent = 0

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
        asyncio.get_event_loop().create_task(self.run_bounty_task(chain))
        asyncio.get_event_loop().create_task(self.run_offer_task())

    async def run_bounty_task(self, chain):
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
            if self.testing and self.bounties_posted >= self.testing:
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
        if self.testing:
            if self.settles_posted > self.testing:
                logging.warning('Scheduled settle, but finished with testing mode')
                return []
            logging.info('Testing mode, %s settles remaining', self.testing - self.settles_posted)

        ret = await self.client.bounties.settle_bounty(bounty_guid, chain)
        if self.testing and self.settles_posted == self.testing:
            logging.info("All testing bounties complete, exiting")
            self.client.stop()
        return ret

    async def next_offer(self):
        """Override this to implement different offer submission queues

        GUID of offer channel to send on is returned from this function, it is the responsibility of the derived class to create and track open offer channels

        Returns:
            (int, str, int): Tuple of amount, channel_guid, ipfs_uri, None to terminate submission

            amount (int): Amount to place this bounty for
            channel_guid (str): GUID of the offer channel to send on
            ipfs_uri (str): IPFS URI of the artifact to post
        """
        return None

    async def run_offer_task(selfs):
        # HACK: In testing mode we start up ambassador/arbiter/microengine
        # immediately and start submitting bounties, however arbiter has to wait
        # a block for its staking tx to be mined before it starts respoonding.
        # Add in a sleep for now, this will be addressed properly in
        # polyswarm-client#5
        if self.testing > 0:
            logging.info('Waiting for arbiter and microengine')
            await asyncio.sleep(5)

        offer = await self.next_offer()
        while offer is not None:
            # Exit if we are in testing mode
            if self.testing and self.offers_sent >= self.testing:
                logging.info('All testing offers submitted')
                break
            self.offers_sent += 1

            logging.info('Sending offer %s: %s', self.offers_sent, offer)
            amount, channel_guid, ipfs_uri = offer
            channel = self.client.offers.channels.get(channel_guid)

            if not channel:
                logging.error('Could not retrieve open channel ')



            # TODO: Figure out best way to fund ambassador on channel creation
            bounties = await self.client.bounties.post_bounty(amount, ipfs_uri, duration, chain)

            for b in bounties:
                guid = b['guid']
                expiration = int(b['expiration'])

                # Handle any additional steps in derived implementations
                self.on_bounty_posted(guid, amount, ipfs_uri, expiration, chain)

                sb = SettleBounty(guid)
                self.client.schedule(expiration + assertion_reveal_window + arbiter_vote_window, sb, chain)

            bounty = await self.next_bounty(chain)

