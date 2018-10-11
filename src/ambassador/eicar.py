import base64
import logging
import os
import random

from async_generator import async_generator, yield_
from polyswarmclient.ambassador import Ambassador

logger = logging.getLogger(__name__)

EICAR = base64.b64decode(b'WDVPIVAlQEFQWzRcUFpYNTQoUF4pN0NDKTd9JEVJQ0FSLVNUQU5EQVJELUFOVElWSVJVUy1URVNULUZJTEUhJEgrSCo=')
NOT_EICAR = 'this is not malicious'
ARTIFACTS = [('eicar', EICAR), ('not_eicar', NOT_EICAR)]
OFFER_EXPERT = os.getenv('OFFER_EXPERT')


class EicarAmbassador(Ambassador):
    """Ambassador which submits the EICAR test file"""

    @async_generator
    async def bounties(self, chain):
        """Submit either the EICAR test string or a benign sample

        Args:
            chain (str): Chain sample is being requested from
        Returns:
            (int, str, int): Tuple of amount, ipfs_uri, duration, None to terminate submission

        Note:
            | The meaning of the return types are as follows:
            |   - **amount** (*int*): Amount to place this bounty for
            |   - **ipfs_uri** (*str*): IPFS URI of the artifact to post
            |   - **duration** (*int*): Duration of the bounty in blocks
        """
        while True:
            amount = self.client.bounties.parameters[chain]['bounty_amount_minimum']
            filename, content = random.choice(ARTIFACTS)
            duration = 20

            logging.info('Submitting %s', filename)
            ipfs_uri = await self.client.post_artifacts([(filename, content)])
            if not ipfs_uri:
                logging.error('Could not submit artifact to IPFS')
                raise StopAsyncIteration

            await yield_(amount, ipfs_uri, duration)

    async def initialize_offer_channels(self):
        if OFFER_EXPERT:
            # TODO: Parameters
            channel, event = await self.open_offer_channel(OFFER_EXPERT, 100 * 10**18, 10**18, 20)
            logger.info('Waiting on expert %s to join', OFFER_EXPERT)
            await event.wait()

    @async_generator
    async def offers(self):
        while True:
            if not self.open_channels:
                logging.info('No offer channels open, ending offer task')
                raise StopAsyncIteration

            guid = random.choice(list(self.open_channels.keys()))
            channel = self.open_channels.get(guid)
            filename, content = random.choice(ARTIFACTS)

            logger.info('Submitting %s', filename)
            ipfs_uri = await self.client.post_artifacts([(filename, content)])
            if not ipfs_uri:
                logger.error('Could not submit artifact to IPFS')
                return None

            return channel.guid, ipfs_uri, 0
