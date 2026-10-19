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
  # Stage a complete release before updating master. Keep old releases intact.
  (cd "$RELEASE_ASSETS" && shasum -a 256 --check SHA256SUMS.txt)
  tag="instant-sync-${head:0:12}"
  body=$(mktemp)
  trap 'rm -f "$body"' EXIT
  cat > "$body" <<EOF
Automated build of this unofficial Mac Mouse Fix Instant fork, including upstream master at $UPSTREAM_SHA.

Download **Mac-Mouse-Fix-Instant.dmg** below. It contains the freshly built app and helper, locally ad hoc signed. The checksum is in **SHA256SUMS.txt**.

The instant-switching tests, sync safety tests, full Release build, app signature verification, and DMG checksum verification passed before publication. These checks do not replace manual testing on every supported Mac or macOS version.

This remains an experimental fork. It is not Developer ID signed or notarized. macOS may require explicit approval, and replacing the helper can require granting Accessibility permission again. Back up existing app settings before updating. In Buttons, select **Spaces & Mission Control (Instant)** for **Click and Drag**.

Mac Mouse Fix's original licensing, trial, and payment systems remain active. Credits: [Mac Mouse Fix](https://github.com/noah-nuebling/mac-mouse-fix) and [InstantSpaceSwitcher](https://github.com/jurplel/InstantSpaceSwitcher).

[Build and validation run](https://github.com/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID)
EOF
  existing=$(gh release view "$tag" --repo "$GITHUB_REPOSITORY" --json isDraft --jq .isDraft 2>/dev/null || true)
  if [[ "$existing" == true ]]; then
    # Only drafts may have assets replaced; published releases remain immutable.
    gh release upload "$tag" "$RELEASE_ASSETS/Mac-Mouse-Fix-Instant.dmg" "$RELEASE_ASSETS/SHA256SUMS.txt" \
      --repo "$GITHUB_REPOSITORY" --clobber
  elif [[ "$existing" != false ]]; then
    gh release create "$tag" "$RELEASE_ASSETS/Mac-Mouse-Fix-Instant.dmg" "$RELEASE_ASSETS/SHA256SUMS.txt" \
      --repo "$GITHUB_REPOSITORY" --target "$head" --draft \
      --title "Mac Mouse Fix Instant · upstream sync ${head:0:7}" --notes-file "$body"
  fi
  # Never force-push master. A concurrent update causes the push to fail.
  git push origin "$head:refs/heads/master"
  gh release edit "$tag" --repo "$GITHUB_REPOSITORY" --draft=false --latest
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
