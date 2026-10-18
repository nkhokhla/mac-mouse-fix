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
if git merge-base --is-ancestor "$upstream" "$base"; then
  echo 'needed=false' >> "$GITHUB_OUTPUT"
  echo 'Upstream is already included.' >> "$GITHUB_STEP_SUMMARY"
  exit 0
fi
echo 'needed=true' >> "$GITHUB_OUTPUT"
git config user.name 'github-actions[bot]'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
git switch --create sync-candidate "$base"
if git merge --no-ff --no-edit "$upstream"; then
  echo 'conflict=false' >> "$GITHUB_OUTPUT"
  head=$(git rev-parse HEAD)
else
  # A PR from the upstream tip shows the conflicting upstream changes using
  # the shared merge base; it does not replace the fork's master branch.
  git merge --abort
  echo 'conflict=true' >> "$GITHUB_OUTPUT"
  head=$upstream
fi
old=$(git ls-remote origin "refs/heads/$branch" | cut -f1)
git push --force-with-lease="refs/heads/$branch:$old" origin "$head:refs/heads/$branch"
printf 'head=%s\n' "$head" >> "$GITHUB_OUTPUT"
