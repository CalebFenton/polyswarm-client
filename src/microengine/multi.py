import asyncio
import logging
import microengine
import os

from polyswarmclient.microengine import Microengine
from microengine.clamav import ClamavScanner
from microengine.yara import YaraScanner

logger = logging.getLogger(__name__)  # Initialize logger
BACKENDS = [ClamavScanner, YaraScanner]


class MultiMicroengine(Microengine):
    """Microengine which aggregates multiple sub-microengines"""

    def __init__(self, client, testing=0, scanner=None, chains={'home'}):
        """Initialize a multi-backend microengine

        Args:
            client (polyswwarmclient.Client): Client to use
            testing (int): How many test bounties to respond to
            chains (set[str]): Chain(s) to operate on
        """
        super().__init__(client, testing, None, chains)
        self.backends = [cls() for cls in BACKENDS]

    async def scan(self, guid, content, chain):
        """Scan an artifact with our chosen backends.

        Args:
            guid (str): GUID of the bounty under analysis, use to track artifacts in the same bounty
            content (bytes): Content of the artifact to be scan
            chain (str): Chain sample is being sent from

        Returns:
            (bool, bool, str): Tuple of bit, verdict, metadata

        Note:
            | The meaning of the return types are as follows:
            |   - **bit** (*bool*): Whether to include this artifact in the assertion or not
            |   - **verdict** (*bool*): Whether this artifact is malicious or not
            |   - **metadata** (*str*): Optional metadata about this artifact
        """
        results = await asyncio.gather(*[backend.scan(guid, content, chain) for backend in self.backends])

        # Unzip the result tuples
        bits, verdicts, metadatas = tuple(zip(*results))
        return any(bits), any(verdicts), ';'.join(metadatas)
