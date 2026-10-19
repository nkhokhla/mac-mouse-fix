"""Run only in the isolated signing job, never while building upstream code."""
import base64
from datetime import datetime, timezone
from email.utils import format_datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

PUBLIC_KEY = "Y6vB4d+BQqGA41GN+4cgKipNYUdW6fNj4ezAxSPKjPA="
REPO = "nkhokhla/mac-mouse-fix"
SPARKLE = "http://www.andymatuschak.org/xml-namespaces/sparkle"
ET.register_namespace("sparkle", SPARKLE)


def make_appcast(metadata):
    commit = metadata["commit"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Invalid source commit")
    if not re.fullmatch(r"[0-9]+", str(metadata["build"])):
        raise ValueError("Invalid build number")
    if metadata["public_key"] != PUBLIC_KEY:
        raise ValueError("The app does not contain the fork's public key")
    if len(base64.b64decode(metadata["signature"], validate=True)) != 64:
        raise ValueError("Invalid Ed25519 signature encoding")
    tag = "instant-sync-" + commit[:12]
    url = f"https://github.com/{REPO}/releases/download/{tag}/Mac-Mouse-Fix-Instant.dmg"
    root = ET.Element("rss", version="2.0")
    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = "Mac Mouse Fix Instant updates"
    ET.SubElement(channel, "link").text = f"https://github.com/{REPO}/releases"
    item = ET.SubElement(channel, "item")
    ET.SubElement(item, "title").text = f"Mac Mouse Fix Instant {metadata['version']} ({metadata['build']})"
    ET.SubElement(item, "pubDate").text = format_datetime(datetime.now(timezone.utc))
    ET.SubElement(item, f"{{{SPARKLE}}}releaseNotesLink").text = f"https://github.com/{REPO}/releases/tag/{tag}"
    ET.SubElement(item, f"{{{SPARKLE}}}minimumSystemVersion").text = metadata["minimum_system_version"]
    ET.SubElement(item, "enclosure", {
        "url": url, "length": str(metadata["length"]), "type": "application/octet-stream",
        f"{{{SPARKLE}}}version": str(metadata["build"]),
        f"{{{SPARKLE}}}shortVersionString": metadata["version"],
        f"{{{SPARKLE}}}edSignature": metadata["signature"],
    })
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def main():
    directory = Path(sys.argv[1])
    metadata = json.loads((directory / "release.json").read_text())
    secret = os.environ.pop("SPARKLE_PRIVATE_KEY").strip()
    raw = base64.b64decode(secret, validate=True)
    if len(raw) != 96 or base64.b64encode(raw[64:]).decode() != PUBLIC_KEY:
        raise SystemExit("Signing key does not match the fork public key")
    dmg = directory / "Mac-Mouse-Fix-Instant.dmg"
    # Capture output and do not echo argv, which includes the private key.
    signed = subprocess.run([sys.argv[2], "-s", secret, str(dmg)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if signed.returncode:
        raise SystemExit("Sparkle signing failed")
    match = re.fullmatch(r'sparkle:edSignature="([A-Za-z0-9+/=]+)" length="([0-9]+)"\s*', signed.stdout)
    if not match or int(match[2]) != dmg.stat().st_size:
        raise SystemExit("Invalid Sparkle signing output")
    metadata.update(signature=match[1], length=dmg.stat().st_size)
    subprocess.run([sys.argv[3], PUBLIC_KEY, metadata["signature"], str(dmg)], check=True)
    (directory / "appcast.xml").write_bytes(make_appcast(metadata))
    (directory / "release.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print("Signed and independently verified update archive")


if __name__ == "__main__":
    main()
