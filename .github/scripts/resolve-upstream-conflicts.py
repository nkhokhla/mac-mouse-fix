"""Resolve documented fork differences, never prefer one side for all source."""
from pathlib import Path
import plistlib
import re
import subprocess
import tempfile

PLISTS = {"App/SupportFiles/Info.plist", "Helper/SupportFiles/Info.plist"}
MISSING = object()
PROJECT = "Mouse Fix.xcodeproj/project.pbxproj"
UUID = r"[A-F0-9]{24}"


def project_section(project, name):
    pattern = r"(/\* Begin " + name + r" section \*/\n)(.*?)(/\* End " + name + r" section \*/)"
    matches = list(re.finditer(pattern, project, re.S))
    if len(matches) != 1:
        raise ValueError(f"Unrecognized Xcode section: {name}")
    return matches[0]


def project_phases(project, name):
    section = project_section(project, name).group(2)
    pattern = r"^\t\t(" + UUID + r") /\* [^\n]* \*/ = \{\n(.*?)^\t\t\};\n"
    phases = {}
    for match in re.finditer(pattern, section, re.M | re.S):
        identifier, body = match.groups()
        if identifier in phases or f"isa = {name};" not in body:
            raise ValueError("Duplicate or unrecognized Xcode phase")
        phases[identifier] = body
    if re.sub(pattern, "", section, flags=re.M | re.S).strip():
        raise ValueError("Unrecognized Xcode phase layout")
    return phases


def project_records(body, build_files=False):
    suffix = r" /\* [^\n]* \*/ = \{isa = PBXBuildFile;[^\n]*\};" if build_files else r" /\* [^\n]* \*/,"
    pattern = r"[ \t]*(" + UUID + r")" + suffix + r"\n"
    records = {}
    for line in body.splitlines(keepends=True):
        if not line.strip():
            continue
        match = re.fullmatch(pattern, line)
        if not match or match[1] in records:
            raise ValueError("Duplicate or unrecognized Xcode file entry")
        records[match[1]] = line
    return records


def project_collections(project):
    """Mask only UUID-keyed file entries; leave settings and target metadata to Git."""
    if "MMF_MERGE_COLLECTION" in project:
        raise ValueError("Unexpected merge placeholder")
    collections = {}
    section = project_section(project, "PBXBuildFile")
    collections["build_files"] = project_records(section[2], build_files=True)
    project = project[:section.start(2)] + "MMF_MERGE_COLLECTION_build_files\n" + project[section.end(2):]
    for name in ("PBXResourcesBuildPhase", "PBXSourcesBuildPhase"):
        # Validate every phase before editing its file-list span.
        phases = project_phases(project, name)
        for identifier, body in phases.items():
            lists = list(re.finditer(r"(^\t\t\tfiles = \(\n)(.*?)(^\t\t\t\);\n)", body, re.M | re.S))
            if len(lists) != 1:
                raise ValueError("Unrecognized Xcode files list")
            files = lists[0]
            key = name + "_" + identifier
            collections[key] = project_records(files[2])
            replacement = body[:files.start(2)] + "MMF_MERGE_COLLECTION_" + key + "\n" + body[files.end(2):]
            # Restrict replacement to this phase, including its UUID.
            prefix = re.search(r"^\t\t" + identifier + r" /\* [^\n]* \*/ = \{\n", project, re.M)
            start = prefix.end()
            if project[start:start + len(body)] != body:
                raise ValueError("Unrecognized Xcode phase boundary")
            project = project[:start] + replacement + project[start + len(body):]
    return project, collections


def merge_project(base, ours, theirs):
    """Merge independent file IDs, refusing competing edits to the same ID."""
    try:
        parsed = [project_collections(value.decode()) for value in (base, ours, theirs)]
        if not all(item[1].keys() == parsed[0][1].keys() for item in parsed):
            return None  # Adding/removing entire phases needs separate review.
        merged_collections = {}
        for key in parsed[0][1]:
            merged_collections[key] = merge_value(*(item[1][key] for item in parsed))
        with tempfile.TemporaryDirectory() as directory:
            files = [Path(directory) / name for name in ("ours", "base", "theirs")]
            for file, index in zip(files, (1, 0, 2)):
                file.write_text(parsed[index][0])
            merged = subprocess.run(["git", "merge-file", "-p", *map(str, files)],
                                    stdout=subprocess.PIPE, check=False)
        if merged.returncode != 0:
            return None
        result = merged.stdout.decode()
        for key, records in merged_collections.items():
            marker = "MMF_MERGE_COLLECTION_" + key + "\n"
            if result.count(marker) != 1:
                return None
            result = result.replace(marker, "".join(records.values()))
        # Reparse and reject dangling membership after cross-collection edits
        # (for example, one side moves a file while the other deletes it).
        _, collections = project_collections(result)
        for key, records in collections.items():
            if key != "build_files" and not records.keys() <= collections["build_files"].keys():
                return None
        return result.encode()
    except (ValueError, UnicodeError):
        return None


def check_instant_spaces_project(project):
    """Check fork-owned IDs all the way from targets to actual file references."""
    records = project_records(project_section(project, "PBXBuildFile")[2], build_files=True)
    file_refs = project_section(project, "PBXFileReference")[2]
    # These IDs belong to this fork. Regenerating them requires an explicit update
    # to this contract, rather than silently accepting missing build wiring.
    expected = {
        "1F0C64BAEF9957C6996BFB49": ("67CB43409F3559F395916099", "ISS.c"),
        "662B332666E7565B99227603": ("B97E45C481DF595E9168F948", "event_serialize.c"),
        "02DE70D2BA2F5BE59A616DB2": ("91C41E5000D352939A1BA086", "InstantSpaceSwitcher-LICENSE.txt"),
        "D2B5D18719C3514BB93D876D": ("91C41E5000D352939A1BA086", "InstantSpaceSwitcher-LICENSE.txt"),
    }
    for identifier, (file_ref, filename) in expected.items():
        entry = records.get(identifier, "")
        if not re.search(r"fileRef = " + file_ref + r" /\* " + re.escape(filename) + r" \*/;", entry):
            raise ValueError(f"InstantSpaceSwitcher build reference missing or changed: {filename}")
        declarations = re.findall(r"^\t\t" + file_ref + r" /\* [^\n]* \*/ = \{[^\n]*\};$", file_refs, re.M)
        if len(declarations) != 1 or not re.search(r'path = "?' + re.escape(filename) + r'"?;', declarations[0]):
            raise ValueError(f"InstantSpaceSwitcher file path missing or changed: {filename}")
    sources = project_phases(project, "PBXSourcesBuildPhase")
    resources = project_phases(project, "PBXResourcesBuildPhase")
    targets = project_phases(project, "PBXNativeTarget")
    wiring = [
        ("4FCECD7F21092354001F1078", "4FCECD7C21092354001F1078", sources,
         ["1F0C64BAEF9957C6996BFB49", "662B332666E7565B99227603"]),
        ("4FCECD7F21092354001F1078", "4FCECD7E21092354001F1078", resources,
         ["D2B5D18719C3514BB93D876D"]),
        ("4F94F5ED25E5EC2500D9F24A", "4F94F5EC25E5EC2500D9F24A", resources,
         ["02DE70D2BA2F5BE59A616DB2"]),
    ]
    for target, phase, phases, identifiers in wiring:
        phase_lists = re.findall(r"buildPhases = \(\n(.*?)\t\t\t\);", targets.get(target, ""), re.S)
        if len(phase_lists) != 1 or len(re.findall(r"\b" + phase + r"\b", phase_lists[0])) != 1:
            raise ValueError("InstantSpaceSwitcher target build phase missing or duplicated")
        file_lists = re.findall(r"files = \(\n(.*?)\t\t\t\);", phases.get(phase, ""), re.S)
        if len(file_lists) != 1:
            raise ValueError("InstantSpaceSwitcher build phase is missing")
        members = project_records(file_lists[0])
        if any(identifier not in members for identifier in identifiers):
            raise ValueError("InstantSpaceSwitcher source or license missing from its target")


def merge_value(base, ours, theirs, key=""):
    if ours == theirs:
        return ours
    if ours == base:
        return theirs
    if theirs == base:
        return ours
    if key == "CFBundleVersion" and all(
        isinstance(v, str) and re.fullmatch(r"\d+(?:\.\d+)*", v)
        for v in (base, ours, theirs)
    ):
        return max((ours, theirs), key=lambda v: tuple(map(int, v.split("."))))
    if all(isinstance(v, dict) for v in (base, ours, theirs)):
        result = {}
        for name in dict.fromkeys([*theirs, *ours, *base]):
            value = merge_value(base.get(name, MISSING), ours.get(name, MISSING),
                                theirs.get(name, MISSING), name)
            if value is not MISSING:
                result[name] = value
        return result
    raise ValueError(f"Unrecognized conflict at {key}")


def resolve(path, base, ours, theirs):
    if path == PROJECT:
        return merge_project(base, ours, theirs)
    if path == "Readme.md":
        # This README describes the fork; upstream documentation remains linked.
        return ours
    if path in PLISTS:
        merged = merge_value(*(plistlib.loads(v) for v in (base, ours, theirs)))
        return plistlib.dumps(merged, sort_keys=False)
    if path != "Helper/AccessibilityCheck.m":
        return None

    # Known upstream mechanical rename. Three-way merge still decides every
    # other edit; a change to the trusted startup logic must not be swallowed.
    old, new = b"GlobalEventTapThread", b"IOThread"
    if old not in base or old not in ours or old in theirs:
        return None
    if any(len(re.findall(rb"^\s*\[IOThread " + method + rb"\];\s*$", theirs, re.M)) != 1
           for method in (b"load_Manual", b"start")):
        return None
    with tempfile.TemporaryDirectory() as directory:
        files = [Path(directory) / name for name in ("ours", "base", "theirs")]
        for file, value in zip(files, (ours.replace(old, new), base.replace(old, new), theirs)):
            file.write_bytes(value)
        merged = subprocess.run(["git", "merge-file", "-p", *map(str, files)],
                                stdout=subprocess.PIPE, check=False)
    if merged.returncode != 0:
        return None
    guard = rb"if\s*\(isTrusted\)\s*\{\s*_enableRunLoopAsserts\s*=\s*1;\s*\[IOThread start\];\s*\}"
    if not re.search(guard, merged.stdout):
        return None
    return merged.stdout


def main():
    paths = subprocess.check_output(
        ["git", "diff", "--name-only", "--diff-filter=U", "-z"]
    ).decode().split("\0")
    for path in filter(None, paths):
        try:
            stages = [subprocess.check_output(["git", "show", f":{stage}:{path}"],
                                              stderr=subprocess.DEVNULL) for stage in (1, 2, 3)]
            result = resolve(path, *stages)
            if result is None:
                continue
            Path(path).write_bytes(result)
            subprocess.run(["git", "add", "--", path], check=True)
            print(f"Resolved known fork difference: {path}")
        except (ValueError, plistlib.InvalidFileException, subprocess.CalledProcessError) as error:
            print(f"Needs review: {path}: {error}")
    return bool(subprocess.check_output(["git", "ls-files", "-u"]))


if __name__ == "__main__":
    raise SystemExit(main())
