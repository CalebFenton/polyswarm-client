import asyncio
import json
import logging
import websockets

from polyswarmclient import events

from web3 import Web3
w3 = Web3()

# Offers only take place on the home chain
CHAIN = 'home'

class OfferChannel(object):
    def __init__(self, client, guid, offer_amount, ambassador_balance, expert_balance, testing=0):
        self.__client = client
        self.guid = guid
        self.offer_amount = offer_amount
        self.ambassador_balance = ambassador_balance
        self.expert_balance = expert_balance
        self.testing = testing

        self.nonce = 0

        self.last_message = None
        self.event_socket = None
        self.msg_socket = None

        self.on_closed_agreement = events.OnOfferClosedAgreementCallback()
        self.on_settle_started = events.OnOfferSettleStartedCallback()
        self.on_settle_challenged = events.OnOfferSettleChallengedCallback()

    def push_state(self, state):
        # TODO: change to be a persistant database so all the assersions can be saved
        # currently saving just the last state/signature for disputes
        self.last_message = state

    async def close(self):
        if self.event_socket:
            await self.event_socket.close()

        if self.msg_socket:
            await self.msg_socket.close()

    async def send_offer(self, current_state):
        if current_state['state']['nonce'] == self.nonce:
            artifact = self.get_next_artifact()
            if artifact:
                offer_state = dict(self.last_message['state'])
                offer_state['close_flag'] = 1
                offer_state['artifact_hash'] = artifact.uri
                # This is the updated nonce
                offer_state['nonce'] = self.nonce
                offer_state['offer_amount'] = self.offer_amount
                offer_state['guid'] = str(self.guid.int)

                # Delete previous offer verdicts/mask
                if 'verdicts' in offer_state:
                    del offer_state['verdicts']

                if 'mask' in offer_state:
                    del offer_state['mask']

                state = await self.__client.generate_state(offer_state)
                sig = self.__client.sign_state(state)

                sig['type'] = 'offer'
                sig['artifact'] = artifact.uri

                logging.info('Sending New Offer: \n%s', offer_state)

                await self.msg_socket.send(
                    json.dumps(sig)
                )


    async def listen_for_events(self):
        """Listen for offer events via websocket connection to polyswarmd"""
        assert(self.polyswarmd_uri.startswith('http'))

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
                    logging.error('Invalid offer event response from polyswarmd')
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
        assert(self.polyswarmd_uri.startswith('http'))

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
                    msg_type = msg.get('type')
                    state = msg.get('state')
                except json.JSONDecodeError:
                    logging.error('Invalid offer message response from polyswarmd: %s', resp)
                    continue

                if msg_type == 'decline':
                    pass
                elif msg_type == 'accept':
                    guid_equal = state['guid'] == self.guid.int
                    nonce_sequential = state['nonce'] == self.nonce + 1
                    ambassador_balance_expected = state['ambassador_balance'] + self.offer_amount == self.ambassador_balance
                    expert_balance_expected = state['expert_balance'] - self.offer_amount == self.expert_balance
                    verdicts_present = 'verdicts' in state

                    accepted = guid_equal and nonce_sequential and ambassador_balance_expected and expert_balance_expected and verdicts_present
                    if accepted:
                        self.nonce += 1

                    if self.testing > 0:
                        self.testing -= 1
                        logging.info('Offers left to send %s', self.testing)

                    if accepted:
                        logging.info('Offer Accepted: \n%s', msg['state'])
                        self.set_state(msg)
                        await self.send_offer(msg)
#                    elif self.last_message['state']['isClosed'] == 1:
#                        logging.info('Rejected State: \n%s', msg['state'])
#                        logging.info('Closing channel with: \n%s', self.last_message['state'])
#                        await close_channel(session, ws, offer_channel, offer_channel.last_message)
#                    else:
#                        logging.info('Rejected State: \n%s', msg['state'])
#                        logging.info('Dispting channel with: \n%s', offer_channel.last_message['state'])
#                        await dispute_channel(session, ws, offer_channel)
#
#                    if offer_channel.testing == 0:
#                        await close_channel(session, ws, offer_channel, offer_channel.last_message)
#                        logging.info('Closing Channel: \n%s', msg['state'])
#                        await offer_channel.close_sockets()
#                        self.__client.stop()

                elif msg['type'] == 'join':
                    self.set_state(msg)
                    logging.info('Channel Joined \n%s', msg['state'])

                    if self.testing > 0:
                        self.testing -= 1
                        logging.info('Offers left to send %s', self.testing)
                    await self.send_offer(msg)

                elif msg['type'] == 'close':
                    #await close_channel(session, ws, offer_channel, msg)
                    await self.close_sockets()
                else:
                    logging.error('Invalid offer message type from polyswarmd: %s', resp)
                    continue


class OffersClient(object):
    def __init__(self, client):
        self.__client = client
        self.channels = {}

    async def generate_state(self, parameters):
        results = await self.__client.make_request('POST', '/offers', CHAIN, json=parameters)
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

    async def create_offer(self, expert_address, settlement_period_length):
        offer = {
            'ambassador': self.__client.address,
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

    async def open_offer(self, guid, signature):
        path = '/offers/{0}/open'.format(guid)
        results = await self.__client.make_request('POST', path, CHAIN, json=signature, track_nonce=True)
        if not results:
            logging.error('Expected transactions, received: %s', results)
            return {}

        transactions = results.get('transactions', [])
        results = await self.__client.post_transactions(transactions, CHAIN)
        if 'offers_opened' not in results:
            logging.error('Expected offer opened, received: %s', results)
        return results.get('offers_opened', [])

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

    async def join_offer(self, guid, signature):
        path = '/offers/{0}/join'.format(guid)
        results = await self.__client.make_request('POST', path, CHAIN, json=signature, track_nonce=True)
        if not results:
            logging.error('Expected transactions, received: %s', results)
            return {}

        transactions = results.get('transactions', [])
        results = await self.__client.post_transactions(transactions, CHAIN)
        if 'offers_joined' not in results:
            logging.error('Expected offer join, received: %s', results)
        return results.get('offers_joined', [])

    async def close_offer(self, guid, signature):
        path = '/offers/{0}/close'.format(guid)
        results = await self.__client.make_request('POST', path, CHAIN, json=signature, track_nonce=True)
        if not results:
            logging.error('Expected transactions, received: %s', results)
            return {}

        transactions = results.get('transactions', [])
        results = await self.__client.post_transactions(transactions, CHAIN)
        if 'offers_closed' not in results:
            logging.error('Expected offer join, received: %s', results)
        return results.get('offers_closed', [])

    async def close_challenged_offer(self, guid, signature):
        path = '/offers/{0}/closeChallenged'.format(guid)
        results = await self.__client.make_request('POST', path, CHAIN, json=signature, track_nonce=True)
        if not results:
            logging.error('Expected transactions, received: %s', results)
            return {}

        transactions = results.get('transactions', [])
        results = await self.__client.post_transactions(transactions, CHAIN)
        return results

    async def settle_offer(self, guid, signature):
        path = '/offers/{0}/settle'.format(guid)
        results = await self.__client.make_request('POST', path, CHAIN, json=signature, track_nonce=True)
        if not results:
            logging.error('Expected transactions, received: %s', results)
            return {}

        transactions = results.get('transactions', [])
        results = await self.__client.post_transactions(transactions, CHAIN)
        if 'offers_settled' not in results:
            logging.error('Expected offer settle, received: %s', results)
        return results.get('offers_settled', [])

    async def challenge_offer(self, guid, signature):
        path = '/offers/{0}/challenge'.format(guid)
        results = await self.__client.make_request('POST', path, CHAIN, json=signature, track_nonce=True)
        if not results:
            logging.error('Expected transactions, received: %s', results)
            return {}

        transactions = results.get('transactions', [])
        results = await self.__client.post_transactions(transactions, CHAIN)
        if 'offers_challenged' not in results:
            logging.error('Expected offer challenge, received: %s', results)
        return results.get('offers_challenged', [])
