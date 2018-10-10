import asyncio
import logging

from async_generator import async_generator
from polyswarmclient import Client
from polyswarmclient.events import SettleBounty

logger = logging.getLogger(__name__)


class Ambassador(object):
    def __init__(self, client, testing=0, chains={'home'}, watchdog=0):
        self.client = client
        self.chains = chains
        self.client.on_run.register(self.__handle_run)
        self.client.on_settle_bounty_due.register(self.__handle_settle_bounty)

        self.pending_channels = {}
        self.open_channels = {}

        self.watchdog = watchdog
        self.first_block = 0
        self.last_bounty_count = 0
        if self.watchdog:
            self.client.on_new_block.register(self.__handle_new_block)

        self.testing = testing
        self.bounties_posted = 0
        self.settles_posted = 0
        self.offers_sent = 0

    @classmethod
    def connect(cls, polyswarmd_addr, keyfile, password, api_key=None, testing=0, insecure_transport=False, chains={'home'}, watchdog=0):
        """Connect the Ambassador to a Client.

        Args:
            polyswarmd_addr (str): URL of polyswarmd you are referring to.
            keyfile (str): Keyfile filename.
            password (str): Password associated with Keyfile.
            api_key (str): Your PolySwarm API key.
            testing (int): Number of testing bounties to use.
            insecure_transport (bool): Allow insecure transport such as HTTP?
            chains (set(str)):  Set of chains you are acting on.

        Returns:
            Ambassador: Ambassador instantiated with a Client.
        """
        client = Client(polyswarmd_addr, keyfile, password, api_key, testing > 0, insecure_transport)
        return cls(client, testing, chains, watchdog)

    def run(self):
        """Run the Client on all of our chains."""
        self.client.run(self.chains)

    async def __handle_run(self, chain):
        """
        Asynchronously run tasks on a given chain.

        Args:
            chain (str): Name of the chain to run.
        """
        # asyncio.get_event_loop().create_task(self.run_bounty_task(chain))
        asyncio.get_event_loop().create_task(self.run_offer_task())

    async def run_bounty_task(self, chain):
        """
            Iterate through the bounties an Ambassador wants to post on a given chain.
            Post each bounty to polyswarmd and schedule the bounty to be settled.

        Args:
            chain (str): Name of the chain to post bounties to.

        """
        assertion_reveal_window = self.client.bounties.parameters[chain]['assertion_reveal_window']
        arbiter_vote_window = self.client.bounties.parameters[chain]['arbiter_vote_window']

        # HACK: In testing mode we start up ambassador/arbiter/microengine
        # immediately and start submitting bounties, however arbiter has to wait
        # a block for its staking tx to be mined before it starts responding.
        # Add in a sleep for now, this will be addressed properly in
        # polyswarm-client#5
        if self.testing > 0:
            logger.info('Waiting for arbiter and microengine')
            await asyncio.sleep(5)

        async for bounty in self.bounties(chain):
            # Exit if we are in testing mode
            if self.testing > 0 and self.bounties_posted >= self.testing:
                logger.info('All testing bounties submitted')
                break
            self.bounties_posted += 1

            logger.info('Submitting bounty %s: %s', self.bounties_posted, bounty)
            amount, ipfs_uri, duration = bounty
            bounties = await self.client.bounties.post_bounty(amount, ipfs_uri, duration, chain)

            for b in bounties:
                guid = b['guid']
                expiration = int(b['expiration'])

                # Handle any additional steps in derived implementations
                self.on_bounty_posted(guid, amount, ipfs_uri, expiration, chain)

                sb = SettleBounty(guid)
                self.client.schedule(expiration + assertion_reveal_window + arbiter_vote_window, sb, chain)

    @async_generator
    async def bounties(self, chain):
        """Override this to implement different bounty submission strategies

        Args:
            chain (str): Chain we are operating on

        Yields:
            (int, str, int): Tuple of amount, ipfs_uri, duration, None to terminate submission

        Note:
            | The meaning of the return types are as follows:
            |   - **amount** (*int*): Amount to place this bounty for
            |   - **ipfs_uri** (*str*): IPFS URI of the artifact to post
            |   - **duration** (*int*): Duration of the bounty in blocks
        """
        raise StopAsyncIteration

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

    async def __handle_new_block(self, number, chain):
        if not self.watchdog:
            return

        if not self.first_block:
            self.first_block = number
            return

        blocks = number - self.first_block
        if blocks % self.watchdog == 0 and self.bounties_posted == self.last_bounty_count:
            raise Exception('Bounties not processing, exiting with failure')

        self.last_bounty_count = self.bounties_posted

    async def __handle_settle_bounty(self, bounty_guid, chain):
        """
        When a bounty is scheduled to be settled, actually settle the bounty to the given chain.

        Args:
            bounty_guid (str): GUID of the bounty to be submitted.
            chain (str): Name of the chain where the bounty is to be posted.
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
        if self.testing > 0 and self.settles_posted == self.testing:
            logger.info("All testing bounties complete, exiting")
            self.client.stop()
        return ret

    async def run_offer_task(self):
        # HACK: In testing mode we start up ambassador/arbiter/microengine
        # immediately and start submitting bounties, however arbiter has to wait
        # a block for its staking tx to be mined before it starts respoonding.
        # Add in a sleep for now, this will be addressed properly in
        # polyswarm-client#5
        if self.testing > 0:
            logging.info('Waiting for arbiter and microengine')
            await asyncio.sleep(5)

        await self.initialize_offer_channels()

        logging.info('Waiting for event channels to be set up')
        await self.offers_ready.wait()

        async for offer in self.offers():
            # Exit if we are in testing mode
            if self.testing and self.offers_sent >= self.testing:
                logging.info('All testing offers submitted')
                break
            self.offers_sent += 1

            logging.info('Sending offer %s: %s', self.offers_sent, offer)
            channel_guid, ipfs_uri, amount = offer

            # TODO: Figure out best way to fund ambassador on channel creation
            channel = self.client.offers.channels.get(channel_guid)
            if not channel:
                logging.error('Could not retrieve open channel')
                continue

            await channel.send_offer(amount, ipfs_uri)

    async def open_offer_channel(self, expert_address, ambassador_balance, initial_offer_amount, settlement_period_length):
        # Create and open an offer with offersclient, then watch for an expert to join
        guid = await self.client.offers.create_and_open(expert_address, ambassador_balance, initial_offer_amount, settlement_period_length)
        self.pending_channels[guid] = asyncio.Event()
        channel = self.client.offers.channels[guid]
        channel.on_expert_joined_offer.register(self.__handle_expert_joined_offer)
        return self.pending_channels[channel.guid]

    async def __handle_expert_joined_offer(self, guid):
        logger.info('EXPERT JOINED OFFER: %s', guid)
        channel, event = self.pending_channels.get(guid)
        if not event:
            logger.warning('Expert joined invalid channel')
            return
        self.open_channels[guid] = channel
        event.set()

    async def initialize_offer_channels(self):
        pass

    @async_generator
    async def offers(self):
        """Override this to implement different offer submission queues

        GUID of offer channel to send on is returned from this function, it is the responsibility of
        the derived class to create and track open offer channels

        Yields:
            (int, str, int): Tuple of amount, channel_guid, ipfs_uri, None to terminate submission

        Note:
            | The meaning of the return types are as follows:
            |   - **channel_guid** (*str*): GUID of the offer channel to send on
            |   - **ipfs_uri** (*str*): IPFS URI of the artifact to post
            |   - **amount** (*int*): Amount to place this bounty for
        """
        raise StopAsyncIteration
