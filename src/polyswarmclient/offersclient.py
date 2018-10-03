import asyncio
import json
import logging
import websockets

from polyswarmclient import events
from uuid import UUID

from web3 import Web3

w3 = Web3()

# Offers only take place on the home chain
CHAIN = 'home'


class OfferChannel(object):
    def __init__(self, client, guid, ambassador_balance, expert_balance, is_ambassador, nonce=0):
        self.__client = client
        self.guid = guid
        self.ambassador_balance = ambassador_balance
        self.expert_balance = expert_balance
        self.is_ambassador = is_ambassador
        self.nonce = nonce

        self.is_closed = False
        self.last_message = None
        self.event_socket = None
        self.msg_socket = None

        self.on_closed_agreement = events.OnOfferClosedAgreementCallback()
        self.on_settle_started = events.OnOfferSettleStartedCallback()
        self.on_settle_challenged = events.OnOfferSettleChallengedCallback()
        self.on_received_offer = events.OnReceivedOfferCallback()

    def push_state(self, state):
        # TODO: change to be a persistant database so all the assersions can be saved, channel resume. Currently saving just the last state/signature for disputes
        self.last_message = state

    async def close_sockets(self):
        if self.event_socket:
            await self.event_socket.close()

        if self.msg_socket:
            await self.msg_socket.close()

    async def send_offer(self, offer_amount, ipfs_uri):
        if not self.is_ambassador:
            logging.error('Attempted to send offer as an expert')
            return

        if self.is_closed or not self.last_message:
            logging.error('Attempted to send offer on invalid channel')
            return

        if not self.last_message['type'] != 'accept':
            logging.error('Attempted to send an offer while one is already pending')
            return

        offer_state = dict(self.last_message['state'])
        offer_state['close_flag'] = 1
        offer_state['artifact_hash'] = ipfs_uri
        # This is the updated nonce
        offer_state['nonce'] = self.nonce
        offer_state['offer_amount'] = offer_amount
        offer_state['guid'] = str(self.guid.int)

        # Delete previous offer verdicts/mask
        if 'verdicts' in offer_state:
            del offer_state['verdicts']

        if 'mask' in offer_state:
            del offer_state['mask']

        state = await self.__client.generate_state(offer_state)
        sig = self.__client.sign_state(state)

        sig['type'] = 'offer'
        sig['artifact'] = ipfs_uri

        logging.info('Sending New Offer: \n%s', offer_state)

        await self.msg_socket.send(
            json.dumps(sig)
        )

    async def accept_offer(self, offer_amount, ipfs_uri):
        if self.is_ambassador:
            logging.error('Attempted to accept offer as an expert')
            return

        if self.is_closed or not self.last_message:
            logging.error('Attempted to accept offer on invalid channel')
            return

        if not self.last_message['type'] != 'offer':
            logging.error('Attempted to accept a non-existing offer')
            return

        # FIXME
        offer_state = dict(self.last_message['state'])
        state = await self.__client.generate_state(offer_state)
        sig = self.__client.sign_state(state)

        await self.msg_socket.send(
            json.dumps(sig)
        )

    async def dispute_offer(self):
        # FIXME
        return

    def check_state(self, state):
        guid_equal = state['guid'] == self.guid.int
        nonce_sequential = state['nonce'] == self.nonce + 1
        ambassador_balance_expected = state['ambassador_balance'] + self.offer_amount == self.ambassador_balance
        expert_balance_expected = state['expert_balance'] - self.offer_amount == self.expert_balance
        verdicts_present = 'verdicts' in state

        accepted = guid_equal and nonce_sequential and ambassador_balance_expected and expert_balance_expected and verdicts_present
        # FIXME
        return True

    def check_offer(self, msg):
        # FIXME
        return True

    def check_payout(self, msg):
        # FIXME
        return True

    async def run(self):
        asyncio.get_event_loop().create_task(self.listen_for_events())
        asyncio.get_event_loop().create_task(self.listen_for_messages())

    async def listen_for_events(self):
        """Listen for offer events via websocket connection to polyswarmd"""
        assert (self.polyswarmd_uri.startswith('http'))

        # http:// -> ws://, https:// -> wss://
        wsuri = '{0}/events/{1}'.format(self.__client.polyswarmd_uri.replace('http', 'ws', 1), self.guid)
        async with websockets.connect(wsuri) as ws:
            self.event_socket = ws

            while not ws.closed:
                try:
                    resp = await ws.recv()
                    resp = json.loads(resp)
                    event = resp.get('event')
                    data = resp.get('data')
                except json.JSONDecodeError:
                    logging.error('Invalid offer message response from polyswarmd: %s', resp)
                    continue

                if event['event'] == 'closed_agreement':
                    logging.info('Received closed agreement on channel %s: %s', self.guid, data)
                    asyncio.get_event_loop().create_task(self.on_closed_agreement.run(**data))
                elif event['event'] == 'settled_started':
                    logging.info('Received settle started on channel %s: %s', self.guid, data)
                    asyncio.get_event_loop().create_task(self.on_settle_started.run(**data))
                elif event['event'] == 'settle_challenged':
                    logging.info('Received settle challenged on channel %s: %s', self.guid, data)
                    asyncio.get_event_loop().create_task(self.on_settle_challenged.run(*data))
                else:
                    logging.error('Invalid offer event type from polyswarmd: %s', resp)
                    continue

    async def listen_for_messages(self, init_message=None):
        """Listen for offer events via websocket connection to polyswarmd"""
        assert (self.polyswarmd_uri.startswith('http'))

        # http:// -> ws://, https:// -> wss://
        wsuri = '{0}/messages/{1}'.format(self.__client.polyswarmd_uri.replace('http', 'ws', 1), self.guid)
        async with websockets.connect(wsuri) as ws:
            self.msg_socket = ws

            # send open message on init
            if init_message:
                logging.info('Sending Open Channel Message: \n%s', init_message['state'])
                await ws.send(json.dumps(init_message))

            while not ws.closed:
                try:
                    resp = await ws.recv()
                    msg = json.loads(resp)
                except json.JSONDecodeError:
                    logging.error('Invalid offer message response from polyswarmd: %s', resp)
                    continue

                if self.is_ambassador:
                    success = self.__handle_message_ambassador(msg)
                else:
                    success = self.__handle_message_expert(msg)

                if not success:
                    break

    async def __handle_message_ambassador(self, msg):
        msg_type = msg.get('type')
        state = msg.get('state')

        if not msg_type or not state:
            return False

        if msg_type == 'decline':
            pass
        elif msg_type == 'accept':
            state_ok = self.check_state(state)
            if state_ok:
                logging.info('Offer Accepted: \n%s', state)

                self.nonce += 1
                self.push_state(msg)

                # FIXME: offer amount configurable
                await self.send_offer(msg, 0)
            elif self.last_message['state']['isClosed'] == 1:
                logging.info('Rejected State: \n%s', msg['state'])
                logging.info('Closing channel with: \n%s', self.last_message['state'])
                await self.close_channel(self.last_message)
            else:
                logging.info('Rejected State: \n%s', msg['state'])
                logging.info('Dispting channel with: \n%s', self.last_message['state'])
                # await dispute_channel(session, ws, offer_channel)
        elif msg_type == 'join':
            self.set_state(msg)
            logging.info('Channel Joined \n%s', msg['state'])
            await self.send_offer(msg)
        elif msg_type == 'close':
            await self.__client.close_offer(self.guid, msg)
            await self.close_sockets()

        return True

    async def __handle_message_expert(self, msg):
        msg_type = msg.get('type')
        state = msg.get('state')

        if not msg_type or not state:
            return False

        if msg_type == 'open':
            sig = self.sign_state(msg['raw_state'])
            await self.__client.join_offer(self.guid.int, sig)
            logging.info('Sending Offer Channel Join Message \n%s', state)
            sig['type'] = 'join'
            self.set_state(msg)
            await self.msg_socket.send(json.dumps(sig))
        elif msg_type == 'offer':
            offer_okay = await self.check_offer(msg)
            if offer_okay:
                logging.info('Received Good Offer:\n%s', msg['state'])
                self.set_state(msg)
                await self.accept_offer(msg)
            else:
                logging.info('Received Bad Offer - Will Dispute:\n%s', msg['state'])
                await self.dispute_channel()
        elif msg_type == 'payout':
            pay_okay = await self.check_payout(msg)
            if pay_okay:
                logging.info('Received Good Pay:\n%s', msg['state'])
                self.set_state(msg)
            else:
                logging.info('Received Bad Pay - Will Dispute:\n%s', msg['state'])
                await self.dispute_channel()
        elif msg_type == 'close':
            sig = self.sign_state(msg['raw_state'])
            sig['type'] = 'close'
            await self.msg_socket.send(json.dumps(sig))
            await self.close_sockets()

        return True


class OffersClient(object):
    def __init__(self, client):
        self.__client = client
        self.channels = {}

    async def generate_state(self, guid, nonce, ambassador_address, expert_address, msig_address, ambassador_balance, expert_balance, offer_amount,
                             close_flag=0, artifact_hash=None, engagement_deadline=None, assertion_deadline=None, mask=None, verdicts=None, metadata=None):
        """Generate state string from parameters

        Args:
            guid (str): GUID of the offer
            nonce (int): Nonce of the message
            ambassador_address (str): Address of the ambassador
            expert_address (str): Address of the expert
            msig_address (str): Address of the multisig contract
            ambassador_balancee (int): Current ambassador balance
            expert_balance (int): Current expert balance
            offer_amount (int): Amount to offer
            close_flag (bool): Should the channel be closed
            artifact_hash (str): Artifact hash of the artifact to scan
            engagement_deadline (int): Deadline for engagement
            assertion_deadline (int): Deadline for assertion
            mask (List[bool]): Artifacts being asserted on
            verdicts (List[bool]): Malicious or benign assertions
            metadata (str): Optional metadata about each artifact

        Returns:
            (str): State string generaetd by polyswarmd compatible with the offers contracts
        """
        state = {
            'guid': str(guid.int),
            'nonce': nonce,
            'ambassador': ambassador_address,
            'expert': expert_address,
            'msig_address': msig_address,
            'ambassador_balance': ambassador_balance,
            'expert_balance': expert_balance,
            'offer_amount': offer_amount,
            'close_flag': close_flag,
        }
        if artifact_hash is not None:
            state['artifact_hash'] = artifact_hash
        if engagement_deadline is not None:
            state['engagement_deadline'] = engagement_deadline
        if assertion_deadline is not None:
            state['assertion_deadline'] = assertion_deadline
        if mask is not None:
            state['mask'] = mask
        if verdicts is not None:
            state['verdicts'] = verdicts
        if metadata is not None:
            state['meta_data'] = metadata

        results = await self.__client.make_request('POST', '/offers/state', CHAIN, json=state)
        if not results:
            logging.error('Expected offer state, received: %s', results)
            return None

        return results.get('state')

    def sign_state(self, state):
        def to_32byte_hex(val):
            return w3.toHex(w3.toBytes(val).rjust(32, b'\0'))

        state_hash = to_32byte_hex(w3.sha3(hexstr=state))
        state_hash = w3.eth.account.defunct_hash_message(hexstr=state_hash)
        sig = w3.eth.account.signHash((state_hash), private_key=self.__client.priv_key)

        return {'r': w3.toHex(sig.r), 'v': sig.v, 's': w3.toHex(sig.s), 'state': state}

    async def __create_offer(self, expert_address, settlement_period_length):
        offer = {
            'ambassador': self.__client.account,
            'expert': expert_address,
            'settlementPeriodLength': settlement_period_length,
        }
        results = await self.__client.make_request('POST', '/offers', CHAIN, json=offer, track_nonce=True)
        if not results:
            logging.error('Expected transactions, received: %s', results)
            return {}

        transactions = results.get('transactions', [])
        results = await self.__client.post_transactions(transactions, CHAIN)
        if 'offers_initialized' not in results:
            logging.error('Expected offer initialized, received: %s', results)
        return results.get('offers_initialized', [])

    async def __open_offer(self, guid, signed_state):
        path = '/offers/{0}/open'.format(guid)
        results = await self.__client.make_request('POST', path, CHAIN, json=signed_state, track_nonce=True)
        if not results:
            logging.error('Expected transactions, received: %s', results)
            return {}

        transactions = results.get('transactions', [])
        results = await self.__client.post_transactions(transactions, CHAIN)
        if 'offers_opened' not in results:
            logging.error('Expected offer opened, received: %s', results)
        return results.get('offers_opened', [])

    async def create_and_open(self, expert_address, ambassador_balance, initial_offer_amount, settlement_period_length):
        offers_created = await self.__create_offer(expert_address, settlement_period_length)
        if not offers_created or not len(offers_created) == 1:
            raise Exception('Could not create offer')
        logging.info('Created offer channel: %s', offers_created)

        offer_info = offers_created.pop()
        # TOOD: String UUIDs from polyswarmd, polyswarm/polyswarmd#63
        guid = UUID(int=offer_info.get('guid'))
        msig = offer_info.get('msig')
        state = await self.generate_state(guid, nonce=0, ambassador_address=self.__client.account, expert_address=expert_address, msig_address=msig,
                                          ambassador_balance=ambassador_balance, expert_balance=0, offer_amount=initial_offer_amount)
        signed_state = self.sign_state(state)

        offers_opened = await self.__open_offer(guid, signed_state)
        logging.info('Opened offer channel: %s', offers_opened)

        channel = OfferChannel(self, guid, ambassador_balance, 0, True)
        asyncio.get_event_loop().create_task(channel.run())
        self.channels[guid] = channel

        return guid

    async def cancel_offer(self, guid):
        path = '/offers/{0}/cancel'.format(guid)
        results = await self.__client.make_request('POST', path, CHAIN, track_nonce=True)
        if not results:
            logging.error('Expected transactions, received: %s', results)
            return {}

        transactions = results.get('transactions', [])
        results = await self.__client.post_transactions(transactions, CHAIN)
        if 'offers_canceled' not in results:
            logging.error('Expected offer canceled, received: %s', results)
        return results.get('offers_canceled', [])

    # TODO Async generator for accepting channels from microengine

    async def __join_offer(self, guid, signed_state):
        path = '/offers/{0}/join'.format(guid)
        results = await self.__client.make_request('POST', path, CHAIN, json=signed_state, track_nonce=True)
        if not results:
            logging.error('Expected transactions, received: %s', results)
            return {}

        transactions = results.get('transactions', [])
        results = await self.__client.post_transactions(transactions, CHAIN)
        if 'offers_joined' not in results:
            logging.error('Expected offer join, received: %s', results)
        return results.get('offers_joined', [])

    async def join_offer(self, guid, msg):
        signed_state = self.sign_state(msg['raw_state'])
        offers_joined = self.__join_offer(guid, signed_state)
        if not offers_joined or len(offers_joined) != 1:
            raise Exception('Could not join offer')

        state = msg['state']
        ambassador_balance = state['ambassador_balance']
        expert_balance = state['expert_balance']

        signed_state['type'] = 'join'

        channel = OfferChannel(self, ambassador_balance, expert_balance, False)
        asyncio.get_event_loop().create_task(channel.run())
        self.channels['guid'] = channel

        return channel

    async def __close_offer(self, guid, signed_state):
        path = '/offers/{0}/close'.format(guid)
        results = await self.__client.make_request('POST', path, CHAIN, json=signed_state, track_nonce=True)
        if not results:
            logging.error('Expected transactions, received: %s', results)
            return {}

        transactions = results.get('transactions', [])
        results = await self.__client.post_transactions(transactions, CHAIN)
        if 'offers_closed' not in results:
            logging.error('Expected offer join, received: %s', results)
        return results.get('offers_closed', [])

    async def __settle_offer(self, guid, signed_state):
        path = '/offers/{0}/settle'.format(guid)
        results = await self.__client.make_request('POST', path, CHAIN, json=signed_state, track_nonce=True)
        if not results:
            logging.error('Expected transactions, received: %s', results)
            return {}

        transactions = results.get('transactions', [])
        results = await self.__client.post_transactions(transactions, CHAIN)
        if 'offers_settled' not in results:
            logging.error('Expected offer settle, received: %s', results)
        return results.get('offers_settled', [])

    async def __challenge_offer(self, guid, signed_state):
        path = '/offers/{0}/challenge'.format(guid)
        results = await self.__client.make_request('POST', path, CHAIN, json=signed_state, track_nonce=True)
        if not results:
            logging.error('Expected transactions, received: %s', results)
            return {}

        transactions = results.get('transactions', [])
        results = await self.__client.post_transactions(transactions, CHAIN)
        if 'offers_challenged' not in results:
            logging.error('Expected offer challenge, received: %s', results)
        return results.get('offers_challenged', [])

    async def __close_challenged_offer(self, guid, signed_state):
        path = '/offers/{0}/closeChallenged'.format(guid)
        results = await self.__client.make_request('POST', path, CHAIN, json=signed_state, track_nonce=True)
        if not results:
            logging.error('Expected transactions, received: %s', results)
            return {}

        transactions = results.get('transactions', [])
        results = await self.__client.post_transactions(transactions, CHAIN)
        return results
