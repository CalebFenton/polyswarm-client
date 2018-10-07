import yara
import tempfile
import os

from polyswarmclient.microengine import Microengine
from polyswarmclient.scanner import Scanner

RULES_DIR = os.getenv('RULES_DIR', 'docker/yara-rules')


class YaraScanner(Scanner):
    def __init__(self):
        self.rules = yara.compile(os.path.join(RULES_DIR, "malware/MALW_Eicar"))

    async def scan(self, guid, content, chain):
        """Scan an artifact with Yara.

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
        matches = self.rules.match(data=content)
        if matches:
            return True, True, ''

        return True, False, ''



class YaraMicroengine(Microengine):
    """Microengine which matches samples against yara rules"""

    def __init__(self, client, testing=0, scanner=None, chains={'home'}):
        """Initialize a Yara microengine

        Args:
            client (`Client`): Client to use
            testing (int): How many test bounties to respond to
            chains (set[str]): Chain(s) to operate on
        """
        scanner = YaraScanner()
        super().__init__(client, testing, scanner, chains)
