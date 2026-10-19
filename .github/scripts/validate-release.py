import base64
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

directory = Path(sys.argv[1])
m = json.loads((directory / "release.json").read_text())
assert m["commit"] == sys.argv[2], "Release is not the tested commit"
assert m["public_key"] == "Y6vB4d+BQqGA41GN+4cgKipNYUdW6fNj4ezAxSPKjPA=", "Wrong signing key"
assert len(base64.b64decode(m["signature"], validate=True)) == 64
dmg = (directory / "Mac-Mouse-Fix-Instant.dmg").read_bytes()
assert len(dmg) == m["length"], "Archive size mismatch"
expected = hashlib.sha256(dmg).hexdigest() + "  Mac-Mouse-Fix-Instant.dmg"
assert (directory / "SHA256SUMS.txt").read_text().strip() == expected, "Archive checksum mismatch"
ns = "{http://www.andymatuschak.org/xml-namespaces/sparkle}"
enclosure = ET.fromstring((directory / "appcast.xml").read_bytes()).find("./channel/item/enclosure")
assert enclosure is not None
assert enclosure.get(ns + "edSignature") == m["signature"]
assert enclosure.get(ns + "version") == str(m["build"])
assert enclosure.get("length") == str(len(dmg))
assert enclosure.get("url") == ("https://github.com/nkhokhla/mac-mouse-fix/releases/download/"
                                "instant-sync-" + m["commit"][:12] + "/Mac-Mouse-Fix-Instant.dmg")
print("Validated signed release metadata and archive checksum")
