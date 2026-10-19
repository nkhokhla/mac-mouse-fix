import importlib.util
from pathlib import Path
import plistlib
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("built_app", Path(__file__).resolve().parents[1] / "check-built-app.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BuiltAppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = Path(self.temp.name) / "Mac Mouse Fix.app"
        self.main = self.app / "Contents/Info.plist"
        self.helper = self.app / "Contents/Library/LoginItems/Mac Mouse Fix Helper.app/Contents/Info.plist"
        self.main.parent.mkdir(parents=True)
        self.helper.parent.mkdir(parents=True)
        self.main.write_bytes(plistlib.dumps({"CFBundleVersion": "3924745228401", "CFBundleShortVersionString": "3.1.0"}))
        self.helper.write_bytes(plistlib.dumps({"CFBundleIdentifier": "com.nkhokhla.mac-mouse-fix.helper.instant", "CFBundleVersion": "25303"}))

    def test_rejects_shipped_regression_before_install(self):
        with self.assertRaisesRegex(ValueError, "CFBundleVersion mismatch"):
            module.check(self.app)

    def test_prepare_uses_processed_main_versions(self):
        module.check(self.app, prepare=True, expected_build="3924745228401")
        self.assertEqual(module.check(self.app), ("3924745228401", "3.1.0"))
        self.assertEqual(plistlib.loads(self.helper.read_bytes())["CFBundleIdentifier"], "com.nkhokhla.mac-mouse-fix.helper.instant")

    def test_rejects_missing_helper_marketing_version(self):
        helper = plistlib.loads(self.helper.read_bytes())
        helper["CFBundleVersion"] = "3924745228401"
        self.helper.write_bytes(plistlib.dumps(helper))
        with self.assertRaisesRegex(ValueError, "CFBundleShortVersionString mismatch"):
            module.check(self.app)

    def test_rejects_stale_main_build_before_preparation(self):
        with self.assertRaisesRegex(ValueError, "requested release build number"):
            module.check(self.app, prepare=True, expected_build="3924745228402")

    def test_rejects_unexpanded_main_version(self):
        main = plistlib.loads(self.main.read_bytes())
        main["CFBundleShortVersionString"] = "$(MARKETING_VERSION)"
        self.main.write_bytes(plistlib.dumps(main))
        with self.assertRaisesRegex(ValueError, "Missing or unresolved"):
            module.check(self.app, prepare=True)
