# Mac Mouse Fix Instant: instant Spaces switching for macOS

An unofficial fork of [Mac Mouse Fix](https://github.com/noah-nuebling/mac-mouse-fix) that adds **instant desktop / Spaces switching with a mouse button and drag**, powered by [InstantSpaceSwitcher](https://github.com/jurplel/InstantSpaceSwitcher).

Switch macOS desktops without the usual sliding transition while keeping the existing vertical Mission Control and App Exposé gestures. The new action is optional; existing mouse button mappings keep their behavior.

[Feature implementation](Helper/Core/Drag/ThreeFingerSwipe/InstantSpaceSwitcher/README.md) · [Upstream pull request #2084](https://github.com/noah-nuebling/mac-mouse-fix/pull/2084) · [Report a fork-specific issue](https://github.com/nkhokhla/mac-mouse-fix/issues)

## Download

[Download the DMG for Apple Silicon and Intel](https://github.com/nkhokhla/mac-mouse-fix/releases/download/v3.1.0-instant.1/Mac-Mouse-Fix-Instant-3.1.0.dmg) · [Release notes and installation instructions](https://github.com/nkhokhla/mac-mouse-fix/releases/tag/v3.1.0-instant.1)

The first release is experimental and has been confirmed working on macOS 27. It is ad hoc signed, not Developer ID signed or notarized; macOS may require explicit approval to open it. Back up an existing installation and settings before replacing it, then grant the custom helper Accessibility permission.

## How to enable instant Spaces switching

In this fork's Mac Mouse Fix app:

1. Open **Buttons**.
2. Find the mouse button's **Click and Drag** action.
3. Choose **Spaces & Mission Control (Instant)**.
4. Hold the button and move the mouse left or right to switch one Space instantly.

Release the button before switching again. Direction follows the macOS natural scrolling preference. Dragging up opens Mission Control; dragging down opens Application Windows / App Exposé through the original continuous gesture handling.

The original **Spaces & Mission Control** option remains available.

## Why this fork exists

Mac Mouse Fix normally simulates a continuous three-finger trackpad swipe for Spaces. This fork adds a separate drag action that calls InstantSpaceSwitcher's switching engine directly, avoiding the normal horizontal transition animation.

You do not need the standalone InstantSpaceSwitcher app running. This integration does not install its global gesture interceptor or change trackpad swipes.

## Compatibility and testing

The feature has been confirmed working in a custom Release installation on **macOS 27**, built with **Xcode 27**. The app and helper compile, and automated tests cover horizontal one-switch behavior, vertical gesture routing, natural scrolling direction, Space boundaries, cancellation, and pointer unfreezing.

Fullscreen Spaces, multiple-display setups, and older macOS versions still need broader manual testing. This is an experimental fork and uses private macOS APIs that may change in future releases.

## Build from source

A prebuilt DMG is available above. To build the app and helper yourself:

```sh
git clone --recurse-submodules https://github.com/nkhokhla/mac-mouse-fix.git
cd mac-mouse-fix
xcodebuild -project 'Mouse Fix.xcodeproj' -scheme App \
  -configuration Release -derivedDataPath build \
  CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO build
```

The resulting app is at `build/Build/Products/Release/Mac Mouse Fix.app`. This command checks the build; a locally installed copy also needs signing and its own helper Accessibility permission. On macOS 27, that permission appears under **Privacy & Security → Device Control and Data Access**.

This fork uses a separate helper identifier to avoid conflicts with the official helper's signing requirements. The main app retains the original settings location. Back up your settings before replacing an existing installation.

Run the automated tests on macOS:

```sh
bash Tests/InstantSpaces/run.sh
```

## Upstream status and credits

The optional instant drag action has been proposed to the original project in [PR #2084](https://github.com/noah-nuebling/mac-mouse-fix/pull/2084). It has not been merged. This fork is not an official Mac Mouse Fix release and is not endorsed by its maintainer.

- **Mac Mouse Fix** by Noah Nuebling provides the app, mouse remapping, smooth scrolling, and gesture handling. See the [original project](https://github.com/noah-nuebling/mac-mouse-fix) and [official website](https://macmousefix.com/).
- **InstantSpaceSwitcher** provides the instant switching engine, pinned here to commit `f7616e42651b1ed8d81625e3640eceed6efa8018`. See its [source](https://github.com/jurplel/InstantSpaceSwitcher) and the [embedded implementation notes](Helper/Core/Drag/ThreeFingerSwipe/InstantSpaceSwitcher/README.md).

## License

Mac Mouse Fix's [original license](License) applies to its code. Its licensing, trial, and payment systems are retained. InstantSpaceSwitcher's MIT license is included in [the vendored source](Helper/Core/Drag/ThreeFingerSwipe/InstantSpaceSwitcher/InstantSpaceSwitcher-LICENSE.txt) and both app bundles.
