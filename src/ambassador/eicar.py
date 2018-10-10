import base64
import logging
import os
import random

from polyswarmclient.ambassador import Ambassador

logger = logging.getLogger(__name__)  # Initialize logger

EICAR = base64.b64decode(b'WDVPIVAlQEFQWzRcUFpYNTQoUF4pN0NDKTd9JEVJQ0FSLVNUQU5EQVJELUFOVElWSVJVUy1URVNULUZJTEUhJEgrSCo=')
NOT_EICAR = 'this is not malicious'
ARTIFACTS = [('eicar', EICAR), ('not_eicar', NOT_EICAR)]
OFFER_EXPERT = os.getenv('OFFER_EXPERT')


class EicarAmbassador(Ambassador):
    """Ambassador which submits the EICAR test file"""

    def __init__(self, client, testing=0, chains={'home'}):
        super().__init__(client, testing, chains)
        self.offer_guid = None

    async def open_offer_channels(self):
        # FIXME: Parameters
        self.offer_guid = await self.client.offers.create_and_open(OFFER_EXPERT, 1000, 1, 10)

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

            async yield amount, ipfs_uri, duration

    async def next_offer(self):
        if not OFFER_EXPERT:
            logging.info('No offer expert configured, ending offer task')
            return None

        if not self.offer_guid:
            return None

        filename, content = random.choice(ARTIFACTS)

        logger.info('Submitting %s', filename)
        ipfs_uri = await self.client.post_artifacts([(filename, content)])
        if not ipfs_uri:
            logger.error('Could not submit artifact to IPFS')
            return None

        return self.offer_guid, ipfs_uri, 0
