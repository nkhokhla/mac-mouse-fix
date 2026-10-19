#!/usr/bin/env bash
set -euo pipefail
# The same signed metadata is served to both preference channels. Neither can
# accidentally return users to the original developer's feed.
assets=$(cd "$1" && pwd)
git fetch origin update-feed:refs/remotes/origin/update-feed
feed=$(mktemp -d)
trap 'git worktree remove --force "$feed" >/dev/null 2>&1 || true' EXIT
git worktree add --detach "$feed" origin/update-feed
python3 - "$feed/release.json" "$assets/release.json" <<'PY'
import json, pathlib, sys
old = pathlib.Path(sys.argv[1])
if old.exists():
    assert int(json.loads(old.read_text())['build']) <= int(json.load(open(sys.argv[2]))['build']), 'Refusing to downgrade the update feed'
PY
cp "$assets/appcast.xml" "$feed/appcast.xml"
cp "$assets/appcast.xml" "$feed/appcast-pre.xml"
cp "$assets/release.json" "$feed/release.json"
git -C "$feed" config user.name 'github-actions[bot]'
git -C "$feed" config user.email '41898282+github-actions[bot]@users.noreply.github.com'
git -C "$feed" add appcast.xml appcast-pre.xml release.json
if ! git -C "$feed" diff --cached --quiet; then
  git -C "$feed" commit -m 'Publish signed Mac Mouse Fix Instant update feed'
  git -C "$feed" push origin HEAD:refs/heads/update-feed
fi
