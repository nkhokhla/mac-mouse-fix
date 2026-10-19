import base64
import importlib.util
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

spec = importlib.util.spec_from_file_location("sign_release", Path(__file__).resolve().parents[1] / "sign-release.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AppcastTests(unittest.TestCase):
    def setUp(self):
        self.metadata = {"commit": "a" * 40, "build": "3924500000000", "version": "3.1.0",
                         "public_key": module.PUBLIC_KEY, "signature": base64.b64encode(bytes(64)).decode(),
                         "minimum_system_version": "10.15", "length": 100}

    def test_signed_release_points_only_to_exact_fork_asset(self):
        root = ET.fromstring(module.make_appcast(self.metadata))
        item = root.find("./channel/item/enclosure")
        self.assertEqual(item.get("url"), "https://github.com/nkhokhla/mac-mouse-fix/releases/download/instant-sync-aaaaaaaaaaaa/Mac-Mouse-Fix-Instant.dmg")
        self.assertEqual(item.get("{" + module.SPARKLE + "}version"), "3924500000000")
        self.assertEqual(item.get("{" + module.SPARKLE + "}edSignature"), self.metadata["signature"])

    def test_original_developers_key_is_rejected(self):
        self.metadata["public_key"] = "ZC69ciDfGYN4t3kwRiPc2SC7J4hchv9w+FfVv59r4+U="
        with self.assertRaises(ValueError): module.make_appcast(self.metadata)

    def test_bad_signature_is_rejected(self):
        self.metadata["signature"] = "bad"
        with self.assertRaises(ValueError): module.make_appcast(self.metadata)

    def test_invalid_commit_cannot_change_download_host(self):
        self.metadata["commit"] = "https://other.example/file"
        with self.assertRaises(ValueError): module.make_appcast(self.metadata)
