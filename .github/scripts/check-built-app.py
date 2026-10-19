"""Validate shipped helper versions; normalize them before code signing if requested."""
import argparse
from pathlib import Path
import plistlib
import re


def check(app, *, prepare=False, expected_build=None):
    app = Path(app)
    main = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    helper_path = app / "Contents/Library/LoginItems/Mac Mouse Fix Helper.app/Contents/Info.plist"
    helper = plistlib.loads(helper_path.read_bytes())
    keys = ("CFBundleVersion", "CFBundleShortVersionString")
    for key in keys:
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", main.get(key, "")):
            raise ValueError(f"Missing or unresolved app {key}")
    if expected_build is not None and main[keys[0]] != str(expected_build):
        raise ValueError("App does not contain the requested release build number")
    if helper.get("CFBundleIdentifier") != "com.nkhokhla.mac-mouse-fix.helper.instant":
        raise ValueError("Unexpected helper identity")
    if prepare:
        # Xcode builds the helper before the app's version-increment phase and
        # expands MARKETING_VERSION in each target separately. Set the final
        # embedded bundle from the processed main Info.plist before signing.
        for key in keys:
            helper[key] = main[key]
        helper_path.write_bytes(plistlib.dumps(helper))
    for key in keys:
        if helper.get(key) != main[key]:
            raise ValueError(f"App/helper {key} mismatch: {main[key]} / {helper.get(key)}")
    return main[keys[0]], main[keys[1]]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app")
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--expected-build")
    args = parser.parse_args()
    build, version = check(args.app, prepare=args.prepare, expected_build=args.expected_build)
    print(f"App and embedded helper verified: {version} ({build})")
