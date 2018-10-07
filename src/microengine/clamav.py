import clamd
import os

from io import BytesIO
from polyswarmclient.microengine import Microengine
from polyswarmclient.scanner import Scanner

CLAMD_HOST = os.getenv('CLAMD_HOST', 'localhost')
CLAMD_PORT = int(os.getenv('CLAMD_PORT', '3310'))
CLAMD_TIMEOUT = 30.0


class ClamavScanner(Scanner):
    def __init__(self):
        self.clamd = clamd.ClamdNetworkSocket(CLAMD_HOST, CLAMD_PORT, CLAMD_TIMEOUT)

    async def scan(self, guid, content, chain):
        """Scan an artifact with ClamAV

        Args:
            guid (str): GUID of the bounty under analysis, use to track artifacts in the same bounty
            content (bytes): Content of the artifact to be scan
            chain (str): Chain we are operating on
        Returns:
            (bool, bool, str): Tuple of bit, verdict, metadata
        
        Note:
            | The meaning of the return types are as follows:
            |   - **bit** (*bool*): Whether to include this artifact in the assertion or not
            |   - **verdict** (*bool*): Whether this artifact is malicious or not
            |   - **metadata** (*str*): Optional metadata about this artifact
        """
        result = self.clamd.instream(BytesIO(content)).get('stream')
        if len(result) >= 2 and result[0] == 'FOUND':
            return True, True, result[1]

        return True, False, ''


class ClamavMicroengine(Microengine):
    """
    Microengine which scans samples through clamd.

    Args:
        client (`Client`): Client to use
        testing (int): How many test bounties to respond to
        chains (set[str]): Chain(s) to operate on
    """

    def __init__(self, client, testing=0, scanner=None, chains={'home'}):
        """Initialize a ClamAV microengine"""
        scanner = ClamavScanner()
        super().__init__(client, testing, scanner, chains)
