"""Resolve documented fork differences, never prefer one side for all source."""
from pathlib import Path
import plistlib
import re
import subprocess
import tempfile

PLISTS = {"App/SupportFiles/Info.plist", "Helper/SupportFiles/Info.plist"}
MISSING = object()


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
