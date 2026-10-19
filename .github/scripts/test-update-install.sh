#!/usr/bin/env bash
set -euo pipefail
assets=$(cd "$1" && pwd)
temp=$(mktemp -d)
trap 'hdiutil detach "$temp/mount" >/dev/null 2>&1 || true; rm -rf "$temp"' EXIT
mkdir "$temp/new" "$temp/old" "$temp/frameworks"
hdiutil attach "$assets/Mac-Mouse-Fix-Instant.dmg" -readonly -nobrowse -mountpoint "$temp/mount"
ditto "$temp/mount/Mac Mouse Fix.app" "$temp/new/Mac Mouse Fix.app"
ditto "$temp/mount/Mac Mouse Fix.app" "$temp/old/Mac Mouse Fix.app"
ditto "$temp/mount/Mac Mouse Fix.app/Contents/Frameworks/Sparkle.framework" "$temp/frameworks/Sparkle.framework"
hdiutil detach "$temp/mount"
version=$(/usr/libexec/PlistBuddy -c 'Print CFBundleVersion' "$temp/old/Mac Mouse Fix.app/Contents/Info.plist")
/usr/libexec/PlistBuddy -c "Set CFBundleVersion $((version-1))" "$temp/old/Mac Mouse Fix.app/Contents/Info.plist"
codesign --force --deep --sign - "$temp/old/Mac Mouse Fix.app"
clang -fobjc-arc -F "$temp/frameworks" -framework Cocoa -framework Sparkle \
  -Wl,-rpath,"$temp/frameworks" .github/scripts/tests/UpdateInstallTest.m -o "$temp/test-update"
signature=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["signature"])' "$assets/release.json")
"$temp/test-update" "$temp/old/Mac Mouse Fix.app" "$temp/new" "$assets/Mac-Mouse-Fix-Instant.dmg" "$signature"
