#!/usr/bin/env bash
# Build, sign, package, and optionally notarize C-SCRuB Desktop for macOS.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="$(dirname "$HERE")"

APP_NAME="C-SCRuB Desktop"
EXE_NAME="C-SCRuB-Desktop"
VERSION="0.3.0"
ARCH="arm64"

BUILD_ENV="$PROJECT/.buildenv"
BUILD_DIR="$PROJECT/build"
DIST_DIR="$PROJECT/dist"
APP="$DIST_DIR/$APP_NAME.app"
DMG="$DIST_DIR/$EXE_NAME-$VERSION-$ARCH.dmg"

DEFAULT_PYTHON="$HOME/.local/share/uv/python/cpython-3.10-macos-aarch64-none/bin/python3.10"
BOOTSTRAP_PYTHON="${PYTHON_BIN:-$DEFAULT_PYTHON}"
SIGN_IDENTITY="${CSC_IDENTITY:-Developer ID Application: Guanlin Chen (2R972T78WJ)}"
NOTARY_PROFILE="${NOTARY_PROFILE:-}"

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "$ARCH" ]]; then
  echo "This build must run on macOS arm64." >&2
  exit 1
fi

if [[ ! -x "$BOOTSTRAP_PYTHON" ]]; then
  echo "Python 3.10 not found at: $BOOTSTRAP_PYTHON" >&2
  echo "Set PYTHON_BIN to a standalone Python 3.10 arm64 executable." >&2
  exit 1
fi

if ! security find-identity -v -p codesigning | grep -Fq "$SIGN_IDENTITY"; then
  echo "Signing identity not found: $SIGN_IDENTITY" >&2
  exit 1
fi

echo "==> clean Python build environment"
rm -rf "$BUILD_ENV"
"$BOOTSTRAP_PYTHON" -m venv "$BUILD_ENV"
PYTHON="$BUILD_ENV/bin/python"

echo "==> install pinned build dependencies"
"$PYTHON" -m pip install --upgrade pip
# Build torchsort against torch 2.4 with a macOS 12 deployment target.
# Newer Xcode rejects an old torch header specialization unless we silence it.
export MACOSX_DEPLOYMENT_TARGET="12.0"
export CXXFLAGS="${CXXFLAGS:-} -Wno-invalid-specialization -Wno-error=invalid-specialization"
"$PYTHON" -m pip install \
  "setuptools==80.10.2" \
  "wheel==0.48.0" \
  "numpy==1.26.4" \
  "torch==2.4.1"
"$PYTHON" -m pip install --no-build-isolation "torchsort==0.1.10"
"$PYTHON" -m pip install -r "$HERE/requirements-build.txt"

echo "==> install C-SCRuB Desktop and external DMC-SCRuB"
"$PYTHON" -m pip install "$PROJECT"

echo "==> generate application icon"
"$PYTHON" "$HERE/make_icons.py"

echo "==> build signed arm64 .app"
rm -rf "$BUILD_DIR" "$DIST_DIR"
mkdir -p "$DIST_DIR"
export PYINSTALLER_CONFIG_DIR="$BUILD_DIR/pyinstaller-cache"
export MACOSX_DEPLOYMENT_TARGET="12.0"
export CSC_IDENTITY="$SIGN_IDENTITY"
cd "$PROJECT"
"$PYTHON" -m PyInstaller \
  --noconfirm \
  --clean \
  --distpath "$DIST_DIR" \
  --workpath "$BUILD_DIR" \
  "$HERE/cscrub.spec"

if [[ ! -d "$APP" ]]; then
  echo "App bundle was not created: $APP" >&2
  exit 1
fi

echo "==> apply final hardened-runtime bundle signature"
xattr -cr "$APP"
codesign \
  --force \
  --options runtime \
  --timestamp \
  --sign "$SIGN_IDENTITY" \
  "$APP"

echo "==> verify application signature"
codesign --verify --deep --strict --verbose=2 "$APP"

echo "==> create drag-to-install DMG"
STAGE="$BUILD_DIR/dmg-stage"
rm -rf "$STAGE" "$DMG"
mkdir -p "$STAGE"
trap 'rm -rf "$STAGE"' EXIT
ditto "$APP" "$STAGE/$APP_NAME.app"
ln -s /Applications "$STAGE/Applications"
hdiutil create \
  -volname "$APP_NAME" \
  -srcfolder "$STAGE" \
  -ov \
  -format UDZO \
  "$DMG"

echo "==> sign DMG"
codesign \
  --force \
  --timestamp \
  --sign "$SIGN_IDENTITY" \
  "$DMG"
codesign --verify --verbose=2 "$DMG"

if [[ -n "$NOTARY_PROFILE" ]]; then
  echo "==> submit DMG for notarization"
  xcrun notarytool submit \
    "$DMG" \
    --keychain-profile "$NOTARY_PROFILE" \
    --wait
  echo "==> staple and validate notarization ticket"
  xcrun stapler staple "$DMG"
  xcrun stapler validate "$DMG"
else
  echo "==> notarization skipped"
  echo "Set NOTARY_PROFILE to a notarytool Keychain profile and rebuild to notarize."
fi

echo
echo "app: $APP"
echo "dmg: $DMG ($(du -sh "$DMG" | cut -f1))"
