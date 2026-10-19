#!/usr/bin/env bash
set -euo pipefail
branch=automation/upstream-sync
git fetch origin master:refs/remotes/origin/master "$branch:refs/remotes/origin/$branch"
current=$(git rev-parse origin/master)
head=$(git rev-parse "origin/$branch")
if [[ "$head" != "$CANDIDATE_SHA" ]]; then
  echo 'The candidate branch changed; refusing to publish a different commit.' >&2
  exit 1
fi
if [[ "$CONFLICT" == false && "$VALIDATION" == success && "$current" == "$BASE_SHA" ]]; then
  git merge-base --is-ancestor "$BASE_SHA" "$head"
  git merge-base --is-ancestor "$UPSTREAM_SHA" "$head"
  export CANDIDATE_SHA="$head"
  bash .github/scripts/publish-fork-release.sh stage
  # Never force-push master. A concurrent update causes the push to fail.
  git push origin "$head:refs/heads/master"
  bash .github/scripts/publish-fork-release.sh publish
  echo "Merged upstream $UPSTREAM_SHA after tests and the Release build passed." >> "$GITHUB_STEP_SUMMARY"
  pr=$(gh pr list --repo "$GITHUB_REPOSITORY" --head "$branch" --base master --state open --json number --jq '.[0].number // empty')
  if [[ -n "$pr" ]]; then
    gh pr close "$pr" --repo "$GITHUB_REPOSITORY" --comment 'The latest upstream sync passed validation and was applied automatically.'
  fi
  exit 0
fi

body=$(mktemp)
trap 'rm -f "$body"' EXIT
cat > "$body" <<EOF
Upstream master has changes that need review before this fork can update.

- Upstream commit: $UPSTREAM_SHA
- Fork base used for the attempt: $BASE_SHA
- Merge conflict: $CONFLICT
- Tests and Release build: $VALIDATION
- Master changed during validation: $([[ "$current" != "$BASE_SHA" ]] && echo yes || echo no)

Master was left unchanged. Resolve conflicts or validation failures before merging.
No new DMG is published until merge conflicts and validation failures are resolved.

[Workflow run](https://github.com/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID)
EOF
pr=$(gh pr list --repo "$GITHUB_REPOSITORY" --head "$branch" --base master --state open --json number --jq '.[0].number // empty')
if [[ -n "$pr" ]]; then
  gh pr edit "$pr" --repo "$GITHUB_REPOSITORY" --body-file "$body"
else
  gh pr create --repo "$GITHUB_REPOSITORY" --head "$branch" --base master \
    --title 'Review upstream Mac Mouse Fix updates' --body-file "$body"
fi
echo 'Upstream sync needs review. See the open sync PR.' >> "$GITHUB_STEP_SUMMARY"
