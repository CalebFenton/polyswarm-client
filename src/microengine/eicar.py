import base64
import logging
import os

from polyswarmartifact import ArtifactType
from polyswarmartifact.schema.verdict import Verdict

from polyswarmclient.abstractmicroengine import AbstractMicroengine
from polyswarmclient.abstractscanner import AbstractScanner, ScanResult

logger = logging.getLogger(__name__)
EICAR = base64.b64decode(
    b'WDVPIVAlQEFQWzRcUFpYNTQoUF4pN0NDKTd9JEVJQ0FSLVNUQU5EQVJELUFOVElWSVJVUy1URVNULUZJTEUhJEgrSCo=')


class Scanner(AbstractScanner):

    def __init__(self):
        super(Scanner, self).__init__()

    async def scan(self, guid, artifact_type, content, metadata, chain):
        """Scan an artifact

        Args:
            guid (str): GUID of the bounty under analysis, use to track artifacts in the same bounty
            artifact_type (ArtifactType): Artifact type for the bounty being scanned
            content (bytes): Content of the artifact to be scan
            metadata (dict) Dict of metadata for the artifact
            chain (str): Chain we are operating on
        Returns:
            ScanResult: Result of this scan
        """
        sysname, _, _, _, machine = os.uname()
        metadata = Verdict().set_scanner(operating_system=sysname,
                                         architecture=machine)

        if content == EICAR:
            metadata.set_malware_family('Eicar Test File')
            return ScanResult(bit=True, verdict=True, metadata=metadata.json())

        metadata.set_malware_family('')
        return ScanResult(bit=True, verdict=False, metadata=metadata.json())


class Microengine(AbstractMicroengine):
    """
    Microengine which tests for the EICAR test file.

    Args:
        client (`Client`): Client to use
        testing (int): How many test bounties to respond to
        chains (set[str]): Chain(s) to operate on
    """

    def __init__(self, client, testing=0, scanner=None, chains=None, artifact_types=None, **kwargs):
        """Initialize Scanner"""
        if artifact_types is None:
            artifact_types = [ArtifactType.FILE]
        scanner = Scanner()
        super().__init__(client, testing, scanner, chains, artifact_types, **kwargs)
