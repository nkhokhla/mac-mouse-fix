#!/usr/bin/env bash
set -euo pipefail
mode=${1:-all}
tag="instant-sync-${CANDIDATE_SHA:0:12}"
if [[ "$mode" != publish ]]; then
  python3 .github/scripts/validate-release.py "$RELEASE_ASSETS" "$CANDIDATE_SHA"
  existing=$(gh release view "$tag" --repo "$GITHUB_REPOSITORY" --json isDraft --jq .isDraft 2>/dev/null || true)
  if [[ "$existing" != false ]]; then
    assets=("$RELEASE_ASSETS/Mac-Mouse-Fix-Instant.dmg" "$RELEASE_ASSETS/SHA256SUMS.txt"
            "$RELEASE_ASSETS/appcast.xml" "$RELEASE_ASSETS/release.json")
    if [[ "$existing" == true ]]; then
      gh release upload "$tag" "${assets[@]}" --repo "$GITHUB_REPOSITORY" --clobber
    else
      body=$(mktemp)
      cat > "$body" <<EOF
This unofficial Mac Mouse Fix Instant build includes instant horizontal Spaces switching and in-app updates from this fork's signed Sparkle feed.

Download **Mac-Mouse-Fix-Instant.dmg** below. Existing users of releases without the fork updater must install this build manually once. After that, Check for Updates uses this fork; background checks run while the settings app is open, and installing an update still requires confirmation.

The app is ad hoc signed, not Developer ID signed or notarized. The update archive also has an Ed25519 signature verified against the public key embedded in the app. macOS may require approval to open the app and renewed Accessibility permission for the helper. Back up settings before replacing an installation.

The feature tests, sync safety tests, full Release build, code signature check, DMG verification, and update signature verification passed. These checks do not replace manual testing of every macOS version and display setup.

Source: $CANDIDATE_SHA. [Validation run](https://github.com/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID).

Credits: [Mac Mouse Fix](https://github.com/noah-nuebling/mac-mouse-fix) and [InstantSpaceSwitcher](https://github.com/jurplel/InstantSpaceSwitcher). Original licensing, trial, and payment systems remain active.
EOF
      gh release create "$tag" "${assets[@]}" --repo "$GITHUB_REPOSITORY" \
        --target "$CANDIDATE_SHA" --draft --title "Mac Mouse Fix Instant · ${CANDIDATE_SHA:0:7}" --notes-file "$body"
      rm -f "$body"
    fi
  fi
fi
if [[ "$mode" == stage ]]; then exit 0; fi
gh release edit "$tag" --repo "$GITHUB_REPOSITORY" --draft=false --latest
published=$(mktemp -d)
trap 'rm -rf "$published"' EXIT
# Use the immutable published metadata when recovering a partial publication,
# rather than a rebuilt archive with a different run/build number.
gh release download "$tag" --repo "$GITHUB_REPOSITORY" \
  --pattern appcast.xml --pattern release.json --dir "$published"
python3 - "$published/release.json" "$CANDIDATE_SHA" <<'PY'
import json, sys
assert json.load(open(sys.argv[1]))['commit'] == sys.argv[2], 'Published source mismatch'
PY
bash .github/scripts/publish-update-feed.sh "$published"
