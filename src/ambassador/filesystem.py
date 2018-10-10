import logging
import random
import os

from polyswarmclient.ambassador import Ambassador
from corpus import DownloadToFileSystemCorpus

logger = logging.getLogger(__name__)  # Initialize logger

ARTIFACT_DIRECTORY = os.getenv('ARTIFACT_DIRECTORY', 'docker/artifacts')
ARTIFACT_BLACKLIST = os.getenv('ARTIFACT_BLACKLIST', 'truth.db').split(',')
BOUNTY_TEST_DURATION_BLOCKS = int(os.getenv('BOUNTY_TEST_DURATION_BLOCKS', 5))

class FilesystemAmbassador(Ambassador):
    """Ambassador which submits artifacts from a directory"""

    def __init__(self, client, testing=0, chains={'home'}, watchdog=0):
        """Initialize a filesystem ambassador

        Args:
            client (`Client`): Client to use
            testing (int): How many test bounties to respond to
            chains (set[str]): Chain(s) to operate on
        """
        super().__init__(client, testing, chains, watchdog)

        self.artifacts = []
        u = os.getenv("MALICIOUS_BOOTSTRAP_URL")
        if u:
            logger.info("Unpacking malware corpus at {0}".format(u))
            d = DownloadToFileSystemCorpus()
            d.download_and_unpack()
            bfl = d.get_benign_file_list()
            mfl = d.get_malicious_file_list()
            logger.info("Unpacking complete, {0} malicious and {1} benign files".format(len(mfl), len(bfl)))
            self.artifacts = bfl + mfl
        else:
            for root, dirs, files in os.walk(ARTIFACT_DIRECTORY):
                for f in files:
                    self.artifacts.append(os.path.join(root, f))

    async def next_bounty(self, chain):
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
        amount = self.client.bounties.parameters[chain]['bounty_amount_minimum']
        filename = random.choice(self.artifacts)
        duration = BOUNTY_TEST_DURATION_BLOCKS

        logger.info('Submitting file %s', filename)
        ipfs_uri = await self.client.post_artifacts([(filename, None)])
        if not ipfs_uri:
            logger.error('Could not submit artifact to IPFS')
            return None

        return amount, ipfs_uri, duration
