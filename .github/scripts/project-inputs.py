"""Resolve fork test/build inputs through Xcode groups, never directory guesses."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import shutil

spec = importlib.util.spec_from_file_location(
    "project_policy", Path(__file__).with_name("resolve-upstream-conflicts.py"))
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)

INPUTS = {
    "plugin": "4FF0254D27AFF90800923107",
    "engine": "67CB43409F3559F395916099",
    "serializer": "B97E45C481DF595E9168F948",
    "serializer_header": "52DFB5149F435803AAF336C9",
    "engine_header": "5DC3116E8C965086BADA1227",
    "license": "91C41E5000D352939A1BA086",
}


def field(body, name, default=None):
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    values = re.findall(r"\b" + name + r'\s*=\s*("(?:[^"\\]|\\.)*"|[^;\s]+)\s*;', body)
    if not values and default is not None:
        return default
    if len(values) != 1:
        raise ValueError(f"Missing or ambiguous Xcode field: {name}")
    return json.loads(values[0]) if values[0].startswith('"') else values[0]


def file_paths(project, identifiers):
    groups = policy.project_phases(project, "PBXGroup")
    section = policy.project_section(project, "PBXFileReference")[2]
    files = {}
    for match in re.finditer(r"^\t\t(" + policy.UUID + r") /\* [^\n]* \*/ = \{([^\n]*)\};$", section, re.M):
        if match[1] in files:
            raise ValueError("Duplicate Xcode file reference")
        files[match[1]] = match[2]
    roots = re.findall(r"\bmainGroup = (" + policy.UUID + r")", policy.project_section(project, "PBXProject")[2])
    if len(roots) != 1 or roots[0] not in groups:
        raise ValueError("Missing or ambiguous Xcode main group")
    parents = {}
    for identifier, body in groups.items():
        children = re.findall(r"children = \(\n(.*?)\t\t\t\);", body, re.S)
        if len(children) != 1:
            raise ValueError("Unrecognized Xcode children list")
        children = re.sub(r"/\*.*?\*/", "", children[0], flags=re.S)
        for child in re.findall(policy.UUID, children):
            parents.setdefault(child, []).append(identifier)

    def walk(identifier, visited):
        if identifier in visited:
            raise ValueError("Cycle in Xcode groups")
        body = groups.get(identifier, files.get(identifier))
        if body is None:
            raise ValueError(f"Xcode input no longer exists: {identifier}")
        tree = field(body, "sourceTree")
        path = Path(field(body, "path", ""))
        if path.is_absolute() or ".." in path.parts or "$" in str(path):
            raise ValueError(f"Unsupported Xcode input path: {path}")
        if tree == "SOURCE_ROOT":
            return path
        if tree != "<group>":
            raise ValueError(f"Unsupported Xcode source tree: {tree}")
        if identifier == roots[0]:
            return path
        owners = parents.get(identifier, [])
        if len(owners) != 1:
            raise ValueError(f"Missing or ambiguous parent for Xcode input: {identifier}")
        return walk(owners[0], visited | {identifier}) / path

    return {identifier: walk(identifier, set()) for identifier in identifiers}, files


def input_paths(project, root):
    root = Path(root).resolve()
    paths, files = file_paths(project, INPUTS.values())
    result = {name: root / paths[identifier] for name, identifier in INPUTS.items()}
    # This upstream API is external to the routing behavior under test. Stage
    # its real declaration so the stand-in cannot drift from the actual type.
    if result["plugin"].is_file() and "WarpDeltaCompensator_ReportFreeze" in result["plugin"].read_text():
        headers = [identifier for identifier, body in files.items()
                   if Path(field(body, "path", "")).name == "WarpDeltaCompensator.h"]
        if len(headers) != 1:
            raise ValueError("Missing or ambiguous WarpDeltaCompensator header")
        resolved, _ = file_paths(project, headers)
        result["warp_header"] = root / resolved[headers[0]]
    for name, path in result.items():
        if not path.resolve().is_relative_to(root) or not path.is_file():
            raise ValueError(f"Xcode {name} input is missing or outside the repository: {path}")
    # Keep the engine's own local includes valid, and ensure Xcode and the tests
    # agree on the same embedded copy rather than selecting another by basename.
    engine = result["engine"].parent
    for name, relative in (("serializer", "event_serialize.c"),
                           ("serializer_header", "event_serialize.h"),
                           ("engine_header", "include/ISS.h"),
                           ("license", "InstantSpaceSwitcher-LICENSE.txt")):
        if result[name] != engine / relative:
            raise ValueError(f"Embedded engine layout changed: {name}")
    return result


def stage(inputs, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    outputs = {"plugin": "ModifiedDragOutputThreeFingerSwipe.m", "engine": "InstantSpaceSwitcher/ISS.c",
               "serializer": "InstantSpaceSwitcher/event_serialize.c",
               "serializer_header": "InstantSpaceSwitcher/event_serialize.h",
               "engine_header": "InstantSpaceSwitcher/include/ISS.h",
               "warp_header": "WarpDeltaCompensator.h"}
    for name, relative in outputs.items():
        if name not in inputs:
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(inputs[name], target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--stage", type=Path)
    args = parser.parse_args()
    try:
        inputs = input_paths((args.root / policy.PROJECT).read_text(), args.root)
        if args.stage:
            stage(inputs, args.stage)
    except ValueError as error:
        raise SystemExit(str(error))
    print("Xcode-resolved switching inputs verified")


if __name__ == "__main__":
    main()
