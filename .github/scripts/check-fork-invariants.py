"""Fail a sync if a clean textual merge silently removed fork-critical wiring."""
from pathlib import Path
import importlib.util
import plistlib
import re


def require(condition, message):
    if not condition:
        raise SystemExit(message)


constants = Path("Shared/Constants.h").read_text()
helper_id = "com.nkhokhla.mac-mouse-fix.helper.instant"
for name, identifier in [("kMFBundleIDApp", "com.nuebling.mac-mouse-fix"),
                         ("kMFBundleIDHelper", helper_id),
                         ("kMFLaunchdHelperIdentifierSM", helper_id)]:
    require(re.search(r"#define\s+" + name + r'\s+@"' + re.escape(identifier) + '"', constants),
            f"Fork identity changed: {name}")
service = plistlib.loads(Path("Shared/HelperServices/sm_launchd.plist").read_bytes())
require(service["Label"] == helper_id, "Helper service identity changed")
project = Path("Mouse Fix.xcodeproj/project.pbxproj").read_text()
policy_path = Path(__file__).with_name("resolve-upstream-conflicts.py")
spec = importlib.util.spec_from_file_location("conflict_policy", policy_path)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)
try:
    policy.check_instant_spaces_project(project)
except ValueError as error:
    raise SystemExit(str(error))
print("InstantSpaceSwitcher sources and app/helper license wiring verified")
require(project.count(f'PRODUCT_BUNDLE_IDENTIFIER = "{helper_id}";') == 2,
        "Both helper configurations must retain the fork bundle ID")
source = Path("Helper/AccessibilityCheck.m").read_text()
source = re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.S)
guard = re.search(r"if\s*\(isTrusted\)\s*\{\s*_enableRunLoopAsserts\s*=\s*1;"
                  r"\s*\[(IOThread|GlobalEventTapThread) start\];\s*\}", source)
require(guard, "Accessibility startup guard was removed or changed")
require(source.count(f"[{guard.group(1)} start];") == 1,
        "Input thread must only start inside the Accessibility guard")
versions = [plistlib.loads(Path(path).read_bytes())["CFBundleVersion"] for path in
            ("App/SupportFiles/Info.plist", "Helper/SupportFiles/Info.plist")]
require(versions[0] == versions[1], "App and helper build numbers differ")
print("Fork identity, Accessibility startup guard, and build numbers verified")

app = plistlib.loads(Path("App/SupportFiles/Info.plist").read_bytes())
feed = "https://raw.githubusercontent.com/nkhokhla/mac-mouse-fix/update-feed"
key = "Y6vB4d+BQqGA41GN+4cgKipNYUdW6fNj4ezAxSPKjPA="
require(app["SUFeedURL"] == feed + "/appcast.xml", "App updater left the fork feed")
require(app["SUPublicEDKey"] == key, "App update verification key changed")
require(f'#define kMFUpdateFeedRepoAddressRaw @"{feed}"' in constants, "Runtime updater feed changed")
require(f"#define kSUPublicEDKey {key}" in constants, "Runtime verification key changed")
print("Fork updater feed and public key verified")
