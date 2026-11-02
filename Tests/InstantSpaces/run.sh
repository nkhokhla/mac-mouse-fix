#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
test_dir=$(mktemp -d)
trap 'rm -rf "$test_dir"' EXIT
python3 .github/scripts/project-inputs.py --stage "$test_dir"
clang -Wall -Wextra -Werror \
  -I "$test_dir/InstantSpaceSwitcher" \
  Tests/InstantSpaces/SwitchingTests.c \
  "$test_dir/InstantSpaceSwitcher/event_serialize.c" \
  -framework ApplicationServices -framework CoreFoundation \
  -o "$test_dir/switching-tests"
ISS_FORCE_EVENT_AUGMENTATION=0 "$test_dir/switching-tests"
ISS_FORCE_EVENT_AUGMENTATION=1 "$test_dir/switching-tests"

# Compile the actual output plugin with stand-ins for its external dependencies.
# The full Xcode build separately checks integration with MMF's real headers.
cp Tests/InstantSpaces/Stubs/* "$test_dir/"
clang -fobjc-arc -fmodules -Wall -Wextra -Werror -I "$test_dir" -I "$test_dir/InstantSpaceSwitcher/include" \
  "$test_dir/ModifiedDragOutputThreeFingerSwipe.m" \
  Tests/InstantSpaces/DragRoutingTests.m -framework Cocoa -o "$test_dir/drag-tests"
"$test_dir/drag-tests"
