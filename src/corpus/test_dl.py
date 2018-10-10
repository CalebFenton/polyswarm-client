import logging
import os
import unittest
from corpus import DownloadToFileSystemCorpus

logger = logging.getLogger(__name__)  # Initialize logger


class DownloaderUnitTest(unittest.TestCase):

    def test_download_truth_artifact(self):
        d = DownloadToFileSystemCorpus()
        t = d.download_truth()
        self.assertTrue(os.path.exists(d.truth_db_pth), msg="Couldn't download truth db")

    def test_download_raw_artifacts(self):
        d = DownloadToFileSystemCorpus()
        d.download_and_unpack()

        self.assertTrue(d.get_malicious_file_list())
        self.assertTrue(d.get_benign_file_list())

        d.generate_truth()
        self.assertTrue(os.path.exists(d.truth_db_pth))
