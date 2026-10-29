"""Exercise sync scripts against disposable repositories; never contact GitHub."""
import os
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import plistlib
import base64
import importlib.util
import json

from test_conflict_policy import BASE, OURS, THEIRS
from test_project_policy import PROJECT, BASE_PROJECT, FORK_PROJECT, UPSTREAM_PROJECT, policy

SCRIPTS = Path(__file__).resolve().parents[1]
GIT = shutil.which("git")


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull)
        self.git("init", "-b", "master")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.commit("shared", "base")
        self.commit("Readme.md", "Upstream documentation")
        for path in ("App/SupportFiles/Info.plist", "Helper/SupportFiles/Info.plist"):
            self.commit(path, plistlib.dumps({"CFBundleVersion": "100"}).decode())
        self.commit("Helper/AccessibilityCheck.m", BASE.decode())
        self.commit(PROJECT, BASE_PROJECT.decode())
        self.base = self.git("rev-parse", "HEAD")
        self.git("clone", "--bare", str(self.repo), str(self.root / "upstream"))
        self.git("clone", "--bare", str(self.repo), str(self.root / "origin"))
        self.git("remote", "add", "origin", str(self.root / "origin"))
        self.git("fetch", "origin")
        self.commit(".github/scripts/resolve-upstream-conflicts.py",
                    (SCRIPTS / "resolve-upstream-conflicts.py").read_text())
        self.commit("feature", "instant switching")
        self.commit("Readme.md", "Fork download and feature documentation")
        for path in ("App/SupportFiles/Info.plist", "Helper/SupportFiles/Info.plist"):
            self.commit(path, plistlib.dumps({"CFBundleVersion": "104"}).decode())
        self.commit("Helper/AccessibilityCheck.m", OURS.decode())
        self.git("push", "origin", "master")
        self.fork = self.git("rev-parse", "HEAD")
        # Exercise the real release staging code; replace only the remote feed transport.
        for name in ("publish-fork-release.sh", "validate-release.py"):
            self.commit(".github/scripts/" + name, (SCRIPTS / name).read_text())
        self.commit(".github/scripts/publish-update-feed.sh", "#!/bin/bash\nexit 0\n")
        self.git("push", "origin", "master")
        self.fork = self.git("rev-parse", "HEAD")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        # Rewrite only the known upstream fetch, keeping all merge/push behavior real.
        (self.bin / "git").write_text(
            '#!/bin/bash\nif [[ "$1" == fetch && "$2" == https://github.com/noah-nuebling/mac-mouse-fix.git ]]; then\n'
            ' shift 2\n exec "$REAL_GIT" fetch "$TEST_UPSTREAM" "$@"\nfi\nexec "$REAL_GIT" "$@"\n'
        )
        (self.bin / "gh").write_text(
            '#!/bin/bash\nprintf "%s\\n" "$*" >> "$GH_LOG"\n'
            'if [[ "$1 $2" == "release view" && -n "$TEST_DRAFT" ]]; then echo "$TEST_DRAFT"; fi\n'
            'if [[ "$1 $2" == "release download" ]]; then\n'
            '  while [[ "$1" != --dir ]]; do shift; done; shift\n'
            '  cp "$RELEASE_ASSETS/appcast.xml" "$RELEASE_ASSETS/release.json" "$1/"\nfi\n')
        for file in self.bin.iterdir():
            file.chmod(0o755)
        self.env.update(PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
                        REAL_GIT=GIT, TEST_UPSTREAM=str(self.root / "upstream"),
                        GITHUB_OUTPUT=str(self.root / "output"),
                        GITHUB_STEP_SUMMARY=str(self.root / "summary"),
                        GH_LOG=str(self.root / "gh-log"),
                        GITHUB_REPOSITORY="example/test", GITHUB_RUN_ID="123")
        assets = self.root / "assets"
        assets.mkdir()
        dmg = b"test dmg"
        (assets / "Mac-Mouse-Fix-Instant.dmg").write_bytes(dmg)
        (assets / "SHA256SUMS.txt").write_text(
            hashlib.sha256(dmg).hexdigest() + "  Mac-Mouse-Fix-Instant.dmg\n")
        self.env["RELEASE_ASSETS"] = str(assets)

    def git(self, *args):
        return subprocess.check_output([GIT, *args], cwd=self.repo, env=self.env,
                                       stderr=subprocess.DEVNULL, text=True).strip()

    def commit(self, name, content):
        (self.repo / name).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / name).write_text(content)
        self.git("add", name)
        self.git("commit", "-m", "Test change")

    def upstream_change(self, conflict=False):
        self.git("switch", "--detach", self.base)
        self.commit("shared" if conflict else "upstream-file", "upstream update")
        self.git("push", str(self.root / "upstream"), "HEAD:master")
        self.git("switch", "master")
        if conflict:
            self.commit("shared", "fork update")
            self.git("push", "origin", "master")
            self.fork = self.git("rev-parse", "HEAD")

    def prepare(self):
        subprocess.run(["bash", str(SCRIPTS / "prepare-upstream-sync.sh")],
                       cwd=self.repo, env=self.env, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return dict(line.split("=", 1) for line in (self.root / "output").read_text().splitlines())

    def publish(self, result, validation="success", check=True):
        env = dict(self.env, BASE_SHA=result["base"], UPSTREAM_SHA=result["upstream"],
                   CANDIDATE_SHA=result["head"], CONFLICT=result["conflict"], VALIDATION=validation)
        assets = Path(self.env["RELEASE_ASSETS"])
        metadata = {"commit": result["head"], "build": "40000", "version": "3.1.0",
                    "minimum_system_version": "10.15", "public_key": "Y6vB4d+BQqGA41GN+4cgKipNYUdW6fNj4ezAxSPKjPA=",
                    "signature": base64.b64encode(bytes(64)).decode(), "length": 8}
        spec = importlib.util.spec_from_file_location("sign_release", SCRIPTS / "sign-release.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        (assets / "release.json").write_text(json.dumps(metadata))
        (assets / "appcast.xml").write_bytes(module.make_appcast(metadata))
        return subprocess.run(["bash", str(SCRIPTS / "publish-upstream-sync.sh")],
                              cwd=self.repo, env=env, check=check,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def origin_master(self):
        return self.git("--git-dir=" + str(self.root / "origin"), "rev-parse", "master")

    def test_no_updates(self):
        self.assertEqual(self.prepare()["needed"], "false")

    def test_adjacent_xcode_edits_are_resolved_before_validation(self):
        self.git("switch", "--detach", self.base)
        self.commit(PROJECT, UPSTREAM_PROJECT.decode())
        self.git("push", str(self.root / "upstream"), "HEAD:master")
        self.git("switch", "master")
        self.commit(PROJECT, FORK_PROJECT.decode())
        self.git("push", "origin", "master")
        fork = self.git("rev-parse", "HEAD")
        result = self.prepare()
        self.assertEqual(result["conflict"], "false")
        merged = self.git("show", result["head"] + ":" + PROJECT)
        policy.check_instant_spaces_project(merged)
        self.assertNotIn("mk_timer_notes.md in Resources", merged)
        self.assertEqual(self.origin_master(), fork, "Resolution must still wait for validation")

    def test_competing_xcode_settings_still_open_review_pr(self):
        self.git("switch", "--detach", self.base)
        self.commit(PROJECT, UPSTREAM_PROJECT.decode().replace("buildSetting = base", "buildSetting = upstream"))
        self.git("push", str(self.root / "upstream"), "HEAD:master")
        self.git("switch", "master")
        self.commit(PROJECT, FORK_PROJECT.decode().replace("buildSetting = base", "buildSetting = fork"))
        self.git("push", "origin", "master")
        fork = self.git("rev-parse", "HEAD")
        result = self.prepare()
        self.assertEqual(result["conflict"], "true")
        self.publish(result, validation="skipped")
        self.assertEqual(self.origin_master(), fork)

    def test_clean_merge_preserves_feature_and_updates_after_validation(self):
        self.upstream_change()
        result = self.prepare()
        self.assertEqual(self.origin_master(), self.fork)
        self.assertEqual(self.git("show", result["head"] + ":feature"), "instant switching")
        self.publish(result)
        self.assertEqual(self.origin_master(), result["head"])
        log = (self.root / "gh-log").read_text()
        self.assertIn("release create", log)
        self.assertIn("--draft", log)
        self.assertIn("--draft=false --latest", log)

    def test_conflict_opens_pr_without_changing_master(self):
        self.upstream_change(conflict=True)
        result = self.prepare()
        self.assertEqual(result["conflict"], "true")
        self.publish(result, validation="skipped")
        self.assertEqual(self.origin_master(), self.fork)
        self.assertIn("pr create", (self.root / "gh-log").read_text())

    def test_failed_validation_does_not_update_master(self):
        self.upstream_change()
        self.publish(self.prepare(), validation="failure")
        self.assertEqual(self.origin_master(), self.fork)
        self.assertNotIn("release create", (self.root / "gh-log").read_text())

    def test_corrupt_dmg_prevents_source_update_and_release(self):
        self.upstream_change()
        result = self.prepare()
        (Path(self.env["RELEASE_ASSETS"]) / "Mac-Mouse-Fix-Instant.dmg").write_bytes(b"corrupt")
        self.assertNotEqual(self.publish(result, check=False).returncode, 0)
        self.assertEqual(self.origin_master(), self.fork)
        self.assertFalse((self.root / "gh-log").exists())

    def test_master_update_during_validation_is_not_overwritten(self):
        self.upstream_change()
        result = self.prepare()
        self.git("switch", "master")
        self.commit("concurrent", "new work")
        new_head = self.git("rev-parse", "HEAD")
        self.git("push", "origin", "master")
        self.publish(result)
        self.assertEqual(self.origin_master(), new_head)

    def test_candidate_is_stable_when_retrying_same_merge(self):
        self.upstream_change()
        first = self.prepare()
        self.git("switch", "master")
        self.git("branch", "-D", "sync-candidate")
        self.assertEqual(self.prepare()["head"], first["head"])

    def test_interrupted_release_is_resumed(self):
        self.env["TEST_DRAFT"] = "true"
        result = self.prepare()
        self.assertEqual(result["head"], self.fork)
        self.publish(result)
        log = (self.root / "gh-log").read_text()
        self.assertIn("release upload", log)
        self.assertNotIn("release create", log)
        self.assertIn("--draft=false --latest", log)

    def test_published_release_with_missing_feed_is_recovered_without_replacing_assets(self):
        self.env["TEST_DRAFT"] = "false"
        result = self.prepare()
        self.assertEqual(result["head"], self.fork)
        self.publish(result)
        log = (self.root / "gh-log").read_text()
        self.assertIn("release download", log)
        self.assertNotIn("release upload", log)
        self.assertNotIn("release create", log)

    def test_known_conflicts_merge_and_publish_with_fork_changes_preserved(self):
        self.git("switch", "--detach", self.base)
        self.commit("Readme.md", "New upstream docs")
        for path in ("App/SupportFiles/Info.plist", "Helper/SupportFiles/Info.plist"):
            self.commit(path, plistlib.dumps({"CFBundleVersion": "110", "NewUpstreamKey": True}).decode())
        self.commit("Helper/AccessibilityCheck.m", THEIRS.decode())
        self.git("push", str(self.root / "upstream"), "HEAD:master")
        self.git("switch", "master")
        result = self.prepare()
        self.assertEqual(result["conflict"], "false")
        self.assertEqual(self.git("show", result["head"] + ":Readme.md"), "Fork download and feature documentation")
        for path in ("App/SupportFiles/Info.plist", "Helper/SupportFiles/Info.plist"):
            plist = plistlib.loads(self.git("show", result["head"] + ":" + path).encode())
            self.assertEqual(plist, {"CFBundleVersion": "110", "NewUpstreamKey": True})
        helper = self.git("show", result["head"] + ":Helper/AccessibilityCheck.m")
        self.assertIn("if (isTrusted)", helper)
        self.assertIn("[IOThread start];", helper)
        self.assertIn("newUpstreamWork();", helper)
        self.assertEqual(self.origin_master(), self.fork)
        self.publish(result)
        self.assertEqual(self.origin_master(), result["head"])


if __name__ == "__main__":
    unittest.main()
