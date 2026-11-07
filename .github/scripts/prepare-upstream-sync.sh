#!/usr/bin/env bash
set -euo pipefail

# This script only merges Git objects. Application code runs in a separate,
# read-only validation job before anything can update master.
branch=automation/upstream-sync
git fetch origin master
git fetch https://github.com/noah-nuebling/mac-mouse-fix.git master:refs/remotes/upstream/master
base=$(git rev-parse origin/master)
upstream=$(git rev-parse upstream/master)
printf 'base=%s\nupstream=%s\n' "$base" "$upstream" >> "$GITHUB_OUTPUT"

published_source() {
  gh api "repos/$GITHUB_REPOSITORY/contents/release.json?ref=update-feed" \
    -H 'Accept: application/vnd.github.raw+json' 2>/dev/null | \
    python3 -c 'import json,sys; print(json.load(sys.stdin).get("commit", ""))' 2>/dev/null
}

if git merge-base --is-ancestor "$upstream" "$base"; then
  # Recover if source was pushed but publication was interrupted. The draft
  # tag names the exact validated merge, so newer fork work cannot be replaced.
  draft=$(gh release view "instant-sync-${base:0:12}" --repo "$GITHUB_REPOSITORY" \
    --json isDraft --jq .isDraft 2>/dev/null || true)
  feed_commit=$(published_source || true)
  if [[ "$draft" == true || ( "$draft" == false && "$feed_commit" != "$base" ) ]]; then
    echo 'needed=true' >> "$GITHUB_OUTPUT"
    echo 'conflict=false' >> "$GITHUB_OUTPUT"
    echo "head=$base" >> "$GITHUB_OUTPUT"
    old=$(git ls-remote origin "refs/heads/$branch" | cut -f1)
    git push --force-with-lease="refs/heads/$branch:$old" origin "$base:refs/heads/$branch"
    echo 'Retrying interrupted DMG publication for the current source.' >> "$GITHUB_STEP_SUMMARY"
    exit 0
  fi
  echo 'needed=false' >> "$GITHUB_OUTPUT"
  echo 'Upstream is already included.' >> "$GITHUB_STEP_SUMMARY"
  exit 0
fi
echo 'needed=true' >> "$GITHUB_OUTPUT"
git config user.name 'github-actions[bot]'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
# Keep the policy from the trusted fork base, even if upstream edits workflows.
policy=$(mktemp)
trap 'rm -f "$policy"' EXIT
git show "$base:.github/scripts/resolve-upstream-conflicts.py" > "$policy"
git switch --create sync-candidate "$base"
if git merge --no-ff --no-commit "$upstream" || python3 "$policy"; then
  # A fixed timestamp makes an identical candidate retryable after transient
  # runner failures, instead of manufacturing a new merge/release every attempt.
  timestamp=$(git show -s --format=%ct "$base" "$upstream" | sort -nr | head -n 1)
  GIT_AUTHOR_DATE="@$timestamp +0000" GIT_COMMITTER_DATE="@$timestamp +0000" \
    git commit -m "Merge upstream $upstream"
  echo 'conflict=false' >> "$GITHUB_OUTPUT"
  head=$(git rev-parse HEAD)
  # Classify against the published source so earlier unreleased app changes
  # cannot be hidden by an acknowledgement-only upstream diff.
  feed_commit=$(published_source || true)
  if [[ "$feed_commit" =~ ^[0-9a-f]{40}$ ]] && git merge-base --is-ancestor "$feed_commit" "$base" &&
    python3 - "$feed_commit" "$head" <<'PY'
import re
import subprocess
import sys

records = subprocess.check_output(
    ["git", "diff", "--raw", "--no-renames", "-z", *sys.argv[1:]]
).split(b"\0")[:-1]
allowed = re.compile(rb"(?:Markdown/LocalizedDocuments/[A-Za-z0-9_-]+/)?Acknowledgements\.md")
if not records or len(records) % 2:
    sys.exit(1)
for record, path in zip(records[::2], records[1::2]):
    if not (record.startswith(b":100644 100644 ") and record.endswith(b" M") and allowed.fullmatch(path)):
        sys.exit(1)
PY
  then
    draft=$(gh release view "instant-sync-${base:0:12}" --repo "$GITHUB_REPOSITORY" \
      --json isDraft --jq .isDraft 2>/dev/null || true)
    if [[ "$draft" != true ]]; then
      echo 'acknowledgements_only=true' >> "$GITHUB_OUTPUT"
      echo 'Only published acknowledgement documents changed. No app build is needed.' >> "$GITHUB_STEP_SUMMARY"
    fi
  fi
else
  # A PR from the upstream tip shows the conflicting upstream changes using
  # the shared merge base; it does not replace the fork's master branch.
  echo 'Unresolved source conflicts:' >> "$GITHUB_STEP_SUMMARY"
  git diff --name-only --diff-filter=U >> "$GITHUB_STEP_SUMMARY"
  git merge --abort
  echo 'conflict=true' >> "$GITHUB_OUTPUT"
  head=$upstream
fi
old=$(git ls-remote origin "refs/heads/$branch" | cut -f1)
git push --force-with-lease="refs/heads/$branch:$old" origin "$head:refs/heads/$branch"
printf 'head=%s\n' "$head" >> "$GITHUB_OUTPUT"
