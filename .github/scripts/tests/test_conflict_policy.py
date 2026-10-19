import importlib.util
from pathlib import Path
import plistlib
import unittest

script = Path(__file__).resolve().parents[1] / "resolve-upstream-conflicts.py"
spec = importlib.util.spec_from_file_location("policy", script)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)

BASE = b"""[GlobalEventTapThread load_Manual];
doUnrelatedWork();
unchangedA();
unchangedB();
unchangedC();
unchangedD();
_enableRunLoopAsserts = 1; // Startup assertions
[GlobalEventTapThread start];
"""
OURS = BASE.replace(b"_enableRunLoopAsserts = 1; // Startup assertions\n[GlobalEventTapThread start];",
                    b"if (isTrusted) {\n    _enableRunLoopAsserts = 1;\n    [GlobalEventTapThread start];\n}")
THEIRS = BASE.replace(b"GlobalEventTapThread", b"IOThread").replace(b"doUnrelatedWork", b"newUpstreamWork")


class ConflictPolicyTests(unittest.TestCase):
    def test_fork_readme_is_owned_by_fork(self):
        self.assertEqual(policy.resolve("Readme.md", b"original", b"fork download", b"upstream edit"),
                         b"fork download")

    def test_versions_merge_without_losing_other_keys(self):
        base = {"CFBundleVersion": "100", "OldKey": True}
        ours = dict(base, CFBundleVersion="104", ForkKey="retained")
        theirs = {"CFBundleVersion": "110", "NewKey": "upstream"}
        merged = policy.resolve("App/SupportFiles/Info.plist",
                                *(plistlib.dumps(v) for v in (base, ours, theirs)))
        self.assertEqual(plistlib.loads(merged), {
            "CFBundleVersion": "110", "ForkKey": "retained", "NewKey": "upstream"})

    def test_build_number_does_not_go_backwards(self):
        self.assertEqual(policy.merge_value("100", "120", "110", "CFBundleVersion"), "120")

    def test_unrelated_plist_conflict_requires_review(self):
        with self.assertRaises(ValueError):
            policy.merge_value({"CFBundleIdentifier": "base"},
                               {"CFBundleIdentifier": "fork"}, {"CFBundleIdentifier": "upstream"})

    def test_thread_rename_keeps_guard_and_upstream_work(self):
        result = policy.resolve("Helper/AccessibilityCheck.m", BASE, OURS, THEIRS)
        self.assertIsNotNone(result)
        self.assertIn(b"newUpstreamWork();", result)
        self.assertIn(b"if (isTrusted)", result)
        self.assertIn(b"[IOThread start];", result)
        self.assertNotIn(b"GlobalEventTapThread", result)

    def test_changed_thread_start_logic_requires_review(self):
        changed = THEIRS.replace(b"[IOThread start];", b"[IOThread start];\n[IOThread start];")
        self.assertIsNone(policy.resolve("Helper/AccessibilityCheck.m", BASE, OURS, changed))

    def test_unrelated_source_conflict_requires_review(self):
        self.assertIsNone(policy.resolve("Helper/Core/Drag/ModifiedDrag.m", BASE, OURS, THEIRS))


if __name__ == "__main__":
    unittest.main()
