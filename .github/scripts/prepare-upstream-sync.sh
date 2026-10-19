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
  # Recover if source was pushed but publication was interrupted. The draft
  # tag names the exact validated merge, so newer fork work cannot be replaced.
  draft=$(gh release view "instant-sync-${base:0:12}" --repo "$GITHUB_REPOSITORY" \
    --json isDraft --jq .isDraft 2>/dev/null || true)
  if [[ "$draft" == true ]]; then
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
