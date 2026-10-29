"""Regression coverage for adjacent Xcode edits and missing fork build wiring."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_conflict_policy import policy

PROJECT = "Mouse Fix.xcodeproj/project.pbxproj"
TIMER = "4FFF9F39307B904F00211519"
ISS = "1F0C64BAEF9957C6996BFB49"
EVENT = "662B332666E7565B99227603"
APP_LICENSE = "02DE70D2BA2F5BE59A616DB2"
HELPER_LICENSE = "D2B5D18719C3514BB93D876D"
SOURCE_PHASE = "4FCECD7C21092354001F1078"
APP_RESOURCES = "4F94F5EC25E5EC2500D9F24A"
HELPER_RESOURCES = "4FCECD7E21092354001F1078"
APP_TARGET = "4F94F5ED25E5EC2500D9F24A"
HELPER_TARGET = "4FCECD7F21092354001F1078"
FILES = {
    TIMER: ("4FFF9F38307B904900211519", "mk_timer_notes.md", "Resources"),
    ISS: ("67CB43409F3559F395916099", "ISS.c", "Sources"),
    EVENT: ("B97E45C481DF595E9168F948", "event_serialize.c", "Sources"),
    APP_LICENSE: ("91C41E5000D352939A1BA086", "InstantSpaceSwitcher-LICENSE.txt", "Resources"),
    HELPER_LICENSE: ("91C41E5000D352939A1BA086", "InstantSpaceSwitcher-LICENSE.txt", "Resources"),
}


def member(identifier):
    _, name, kind = FILES[identifier]
    return f"\t\t\t\t{identifier} /* {name} in {kind} */,\n"


def section(name, body):
    return f"/* Begin {name} section */\n{body}/* End {name} section */\n"


def phase(identifier, kind, members, field="files"):
    return (f"\t\t{identifier} /* {kind} */ = {{\n\t\t\tisa = {kind};\n"
            f"\t\t\t{field} = (\n{members}\t\t\t);\n\t\t}};\n")


def project(entries=(TIMER,), sources=(), resources=None, setting="base"):
    if resources is None:
        resources = (TIMER,) if TIMER in entries else ()
    build_files = ""
    # Stable file references keep these fixtures focused on build-file and
    # membership conflicts, matching the two conflicting hunks in the incident.
    refs = {ref: f'\t\t{ref} /* {name} */ = {{isa = PBXFileReference; path = "{name}"; }};\n'
            for ref, name, _ in FILES.values()}
    for identifier in entries:
        ref, name, kind = FILES[identifier]
        build_files += (f"\t\t{identifier} /* {name} in {kind} */ = "
                        f"{{isa = PBXBuildFile; fileRef = {ref} /* {name} */; }};\n")
    targets = ""
    for target, phases in [(APP_TARGET, [APP_RESOURCES]),
                           (HELPER_TARGET, [SOURCE_PHASE, HELPER_RESOURCES])]:
        members = "".join(f"\t\t\t\t{p} /* Phase */,\n" for p in phases)
        targets += phase(target, "PBXNativeTarget", members, "buildPhases")
    return ("// !$*UTF8*$!\n{\n" + section("PBXBuildFile", build_files)
            + section("PBXFileReference", "".join(refs.values()))
            + section("PBXSourcesBuildPhase", phase(SOURCE_PHASE, "PBXSourcesBuildPhase", "".join(map(member, sources))))
            + section("PBXResourcesBuildPhase",
                      phase(APP_RESOURCES, "PBXResourcesBuildPhase", member(APP_LICENSE) if APP_LICENSE in entries else "")
                      + phase(HELPER_RESOURCES, "PBXResourcesBuildPhase", "".join(map(member, resources))))
            + section("PBXNativeTarget", targets)
            + f"buildSetting = {setting};\n}}\n").encode()


# Keep the fork addition immediately beside the upstream deletion, as in the
# October 2026 incident. These small fixtures intentionally cause a Git conflict.
BASE_PROJECT = project()
FORK_PROJECT = project((TIMER, ISS, EVENT, APP_LICENSE, HELPER_LICENSE),
                       (ISS, EVENT), (HELPER_LICENSE, TIMER))
UPSTREAM_PROJECT = project(())


class ProjectPolicyTests(unittest.TestCase):
    def test_adjacent_removal_and_fork_additions_merge_by_id(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / p for p in ("ours", "base", "theirs")]
            for path, value in zip(paths, (FORK_PROJECT, BASE_PROJECT, UPSTREAM_PROJECT)):
                path.write_bytes(value)
            result = subprocess.run(["git", "merge-file", "-p", *map(str, paths)], capture_output=True)
            self.assertGreater(result.returncode, 0, "Fixture must reproduce the Git conflict")
        merged = policy.resolve(PROJECT, BASE_PROJECT, FORK_PROJECT, UPSTREAM_PROJECT)
        self.assertIsNotNone(merged)
        records = policy.project_collections(merged.decode())[1]["build_files"]
        self.assertNotIn(TIMER, records)
        self.assertEqual(set(records), {ISS, EVENT, APP_LICENSE, HELPER_LICENSE})
        policy.check_instant_spaces_project(merged.decode())

    def test_independent_additions_from_both_sides_are_kept(self):
        merged = policy.resolve(PROJECT, project(()), project((ISS,), (ISS,), ()),
                                project((EVENT,), (EVENT,), ()))
        self.assertIsNotNone(merged)
        self.assertEqual(set(policy.project_collections(merged.decode())[1]["build_files"]), {ISS, EVENT})

    def test_competing_edits_to_same_build_file_require_review(self):
        base = project((ISS,), (ISS,), ())
        ours = base.replace(b"isa = PBXBuildFile;", b"isa = PBXBuildFile; settings = {A = 1; };", 1)
        theirs = base.replace(b"isa = PBXBuildFile;", b"isa = PBXBuildFile; settings = {A = 2; };", 1)
        self.assertIsNone(policy.resolve(PROJECT, base, ours, theirs))

    def test_delete_versus_modify_requires_review(self):
        changed = BASE_PROJECT.replace(b"isa = PBXBuildFile;", b"isa = PBXBuildFile; settings = {A = 1; };", 1)
        self.assertIsNone(policy.resolve(PROJECT, BASE_PROJECT, changed, UPSTREAM_PROJECT))

    def test_duplicate_ids_require_review(self):
        line = next(line for line in FORK_PROJECT.splitlines(True) if ISS.encode() in line)
        duplicate = FORK_PROJECT.replace(line, line + line)
        self.assertIsNone(policy.resolve(PROJECT, BASE_PROJECT, duplicate, UPSTREAM_PROJECT))

    def test_unrelated_build_setting_conflict_requires_review(self):
        ours = FORK_PROJECT.replace(b"buildSetting = base", b"buildSetting = fork")
        theirs = UPSTREAM_PROJECT.replace(b"buildSetting = base", b"buildSetting = upstream")
        self.assertIsNone(policy.resolve(PROJECT, BASE_PROJECT, ours, theirs))

    def test_phase_removal_requires_review(self):
        text = UPSTREAM_PROJECT.decode()
        block = phase(SOURCE_PHASE, "PBXSourcesBuildPhase", "")
        self.assertIsNone(policy.resolve(PROJECT, BASE_PROJECT, FORK_PROJECT, text.replace(block, "").encode()))

    def test_unknown_record_layout_requires_review(self):
        multiline = FORK_PROJECT.replace(b"{isa = PBXBuildFile;", b"{\nisa = PBXBuildFile;", 1)
        self.assertIsNone(policy.resolve(PROJECT, BASE_PROJECT, multiline, UPSTREAM_PROJECT))

    def test_competing_membership_edit_requires_review(self):
        base = project((ISS,), (ISS,), ())
        old = member(ISS).encode()
        ours = base.replace(old, old.replace(b"ISS.c", b"Fork.c"))
        theirs = base.replace(old, old.replace(b"ISS.c", b"Upstream.c"))
        self.assertIsNone(policy.resolve(PROJECT, base, ours, theirs))

    def test_move_versus_delete_cannot_leave_dangling_membership(self):
        text = BASE_PROJECT.decode().replace(member(TIMER), "")
        empty = phase(APP_RESOURCES, "PBXResourcesBuildPhase", "")
        moved = text.replace(empty, phase(APP_RESOURCES, "PBXResourcesBuildPhase", member(TIMER)))
        self.assertIsNone(policy.resolve(PROJECT, BASE_PROJECT, moved.encode(), UPSTREAM_PROJECT))

    def test_invariants_accept_complete_wiring(self):
        policy.check_instant_spaces_project(FORK_PROJECT.decode())

    def test_invariants_reject_removed_source_or_license_membership(self):
        for identifier in (ISS, EVENT, APP_LICENSE, HELPER_LICENSE):
            with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                text = FORK_PROJECT.decode().replace(member(identifier), "")
                policy.check_instant_spaces_project(text)

    def test_invariants_reject_removed_target_phase(self):
        text = FORK_PROJECT.decode().replace(f"\t\t\t\t{SOURCE_PHASE} /* Phase */,\n", "")
        with self.assertRaises(ValueError):
            policy.check_instant_spaces_project(text)

    def test_invariants_reject_file_reference_redirect(self):
        text = FORK_PROJECT.decode().replace('path = "ISS.c";', 'path = "Other.c";')
        with self.assertRaises(ValueError):
            policy.check_instant_spaces_project(text)

    def test_invariants_reject_duplicate_phase_membership(self):
        text = FORK_PROJECT.decode().replace(member(ISS), member(ISS) * 2)
        with self.assertRaises(ValueError):
            policy.check_instant_spaces_project(text)


if __name__ == "__main__":
    unittest.main()
