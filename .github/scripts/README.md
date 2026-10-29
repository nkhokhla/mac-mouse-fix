# Upstream sync guardrails

The scheduled sync prepares a merge candidate, runs the fork invariants and
regression tests, builds the Release app and helper, and verifies the packaged
update before publishing. Conflict resolution alone never authorizes publication.

`resolve-upstream-conflicts.py` is extracted from the trusted fork base. Its Xcode
policy merges `PBXBuildFile` entries and Sources/Resources memberships by their
stable object IDs. Independent additions, removals, and edits can coexist even
when Git groups neighboring lines into one conflict. Other project text still
uses Git's three-way merge. Competing edits to the same ID, delete/modify
conflicts, duplicate entries, unfamiliar layouts, phase additions/removals, and
unresolved build settings stop for review.

`check-fork-invariants.py` verifies that the helper target still compiles both
InstantSpaceSwitcher sources and that the app and helper still bundle its
license. It follows target, phase, build-file, and file-reference IDs so entries
left elsewhere in the project cannot disguise missing target membership. These
fork-owned IDs form an explicit contract; update the checks when deliberately
regenerating them. Existing identity, startup, version, and updater checks remain.

The Xcode policy tests reproduce the October 2026 notes-resource deletion beside
fork additions. Sync integration tests verify that this case proceeds to
validation and that incompatible settings still open a review PR without
updating master. To check the guardrails locally:

```sh
python3 -m unittest discover -s .github/scripts/tests -p 'test_*.py'
python3 .github/scripts/check-fork-invariants.py
```

Keep fork-owned entries separate from upstream entries when editing the project
to reduce textual conflicts before the structural fallback is needed.
