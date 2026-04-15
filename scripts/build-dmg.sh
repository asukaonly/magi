#!/usr/bin/env bash
# Build a DMG from the Tauri .app bundle with flat icon rendering.
#
# Tauri's built-in DMG bundler enables Finder's "show icon preview",
# which adds an unwanted 3D shadow effect to the app icon. This script
# creates the DMG manually with showIconPreview disabled.
#
# Usage:
#   ./scripts/build-dmg.sh [--target <triple>]
#
# Examples:
#   ./scripts/build-dmg.sh
#   ./scripts/build-dmg.sh --target aarch64-apple-darwin

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="${ROOT_DIR}/frontend"
TAURI_DIR="${FRONTEND_DIR}/src-tauri"

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
TARGET_TRIPLE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)
      TARGET_TRIPLE="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

if [[ -z "$TARGET_TRIPLE" ]]; then
  TARGET_TRIPLE="$(rustc -vV | grep host | awk '{print $2}')"
fi

# ---------------------------------------------------------------------------
# Resolve paths
# ---------------------------------------------------------------------------

# Read product name and version from tauri.conf.json
PRODUCT_NAME=$(python3 -c "import json; c=json.load(open('${TAURI_DIR}/tauri.conf.json')); print(c['productName'])")
VERSION=$(python3 -c "import json; c=json.load(open('${TAURI_DIR}/tauri.conf.json')); print(c['version'])")

# Tauri outputs to target/<triple>/release/bundle/macos/ when --target is used,
# or target/release/bundle/macos/ otherwise. Check for the actual .app bundle.
BUNDLE_DIR=""
for candidate in \
  "${ROOT_DIR}/target/${TARGET_TRIPLE}/release/bundle/macos" \
  "${ROOT_DIR}/target/release/bundle/macos"; do
  if [[ -d "${candidate}/${PRODUCT_NAME}.app" ]]; then
    BUNDLE_DIR="$candidate"
    break
  fi
done

if [[ -z "$BUNDLE_DIR" ]]; then
  echo "Error: Cannot find ${PRODUCT_NAME}.app bundle. Run 'npm run tauri build' first."
  exit 1
fi

APP_BUNDLE="${BUNDLE_DIR}/${PRODUCT_NAME}.app"

# Determine arch label for the DMG filename
case "$TARGET_TRIPLE" in
  aarch64-*) ARCH_LABEL="aarch64" ;;
  x86_64-*)  ARCH_LABEL="x64" ;;
  *)         ARCH_LABEL="$TARGET_TRIPLE" ;;
esac

DMG_DIR="${BUNDLE_DIR}/../dmg"
mkdir -p "$DMG_DIR"
DMG_FILENAME="${PRODUCT_NAME}_${VERSION}_${ARCH_LABEL}.dmg"
DMG_PATH="${DMG_DIR}/${DMG_FILENAME}"

# Clean up previous DMG
rm -f "$DMG_PATH"

echo "Building DMG: ${DMG_FILENAME}"
echo "  App bundle: ${APP_BUNDLE}"
echo "  Output:     ${DMG_PATH}"

# ---------------------------------------------------------------------------
# DMG settings
# ---------------------------------------------------------------------------
VOLUME_NAME="${PRODUCT_NAME}"
ICON_SIZE=80
TEXT_SIZE=12
WIN_WIDTH=660
WIN_HEIGHT=400
WIN_X=200
WIN_Y=120
APP_X=180
APP_Y=170
APPS_X=480
APPS_Y=170

ICNS_FILE="${TAURI_DIR}/icons/icon.icns"

# ---------------------------------------------------------------------------
# Create temporary writable DMG
# ---------------------------------------------------------------------------
STAGING_DIR=$(mktemp -d)
trap 'rm -rf "$STAGING_DIR"' EXIT

cp -a "$APP_BUNDLE" "${STAGING_DIR}/${PRODUCT_NAME}.app"
ln -s /Applications "${STAGING_DIR}/Applications"

# Estimate size (source + 20 MB headroom)
SIZE_MB=$(( $(du -sm "$STAGING_DIR" | awk '{print $1}') + 20 ))

DMG_TEMP="${DMG_DIR}/rw_${DMG_FILENAME}"
rm -f "$DMG_TEMP"

hdiutil create -srcfolder "$STAGING_DIR" \
  -volname "$VOLUME_NAME" \
  -fs HFS+ -fsargs "-c c=64,a=16,e=16" \
  -format UDRW \
  -size "${SIZE_MB}m" \
  "$DMG_TEMP"

# ---------------------------------------------------------------------------
# Mount and customize Finder view
# ---------------------------------------------------------------------------
DEV_NAME=$(hdiutil attach -readwrite -noverify -noautoopen -nobrowse "$DMG_TEMP" \
  | grep -E '^/dev/' | head -1 | awk '{print $1}')

MOUNT_DIR=$(hdiutil info | grep -E "${DEV_NAME}s" | awk '{print $3}' | xargs)
if [[ -z "$MOUNT_DIR" ]]; then
  MOUNT_DIR=$(hdiutil info | grep -E "${DEV_NAME}" | grep "/Volumes" | awk '{$1=$2=""; print $0}' | xargs)
fi

echo "Mounted at: ${MOUNT_DIR}"

# Set volume icon
if [[ -f "$ICNS_FILE" ]]; then
  cp "$ICNS_FILE" "${MOUNT_DIR}/.VolumeIcon.icns"
  SetFile -c icnC "${MOUNT_DIR}/.VolumeIcon.icns"
fi

# Apply Finder view settings via AppleScript
# Key: "shows icon preview" is set to false to prevent 3D icon rendering
sleep 2
/usr/bin/osascript <<APPLESCRIPT
tell application "Finder"
  tell disk "${VOLUME_NAME}"
    open
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    set the bounds of container window to {${WIN_X}, ${WIN_Y}, $((WIN_X + WIN_WIDTH)), $((WIN_Y + WIN_HEIGHT))}

    set opts to the icon view options of container window
    tell opts
      set icon size to ${ICON_SIZE}
      set text size to ${TEXT_SIZE}
      set arrangement to not arranged
      set shows icon preview to false
    end tell

    set position of item "${PRODUCT_NAME}.app" to {${APP_X}, ${APP_Y}}
    set position of item "Applications" to {${APPS_X}, ${APPS_Y}}

    -- Hide dotfiles by pushing everything off-screen, then repositioning visible items
    set position of every item to {$((WIN_WIDTH + 200)), 100}
    set position of item "${PRODUCT_NAME}.app" to {${APP_X}, ${APP_Y}}
    set position of item "Applications" to {${APPS_X}, ${APPS_Y}}

    close
    open
    set statusbar visible of container window to false
    set the bounds of container window to {${WIN_X}, ${WIN_Y}, $((WIN_X + WIN_WIDTH)), $((WIN_Y + WIN_HEIGHT))}
    close
  end tell
end tell

-- Wait for .DS_Store to be written
delay 3
APPLESCRIPT

echo "Finder customization applied."

# Mark volume as having custom icon
SetFile -a C "$MOUNT_DIR"

# Remove unnecessary fseventsd
rm -rf "${MOUNT_DIR}/.fseventsd" 2>/dev/null || true

sleep 2

# ---------------------------------------------------------------------------
# Unmount & compress
# ---------------------------------------------------------------------------
echo "Unmounting..."
UNMOUNT_ATTEMPTS=0
until hdiutil detach "$DEV_NAME" 2>/dev/null; do
  UNMOUNT_ATTEMPTS=$((UNMOUNT_ATTEMPTS + 1))
  if [[ $UNMOUNT_ATTEMPTS -ge 5 ]]; then
    echo "Error: Failed to unmount after ${UNMOUNT_ATTEMPTS} attempts."
    exit 1
  fi
  echo "  Retrying unmount (attempt ${UNMOUNT_ATTEMPTS})..."
  sleep $((2 ** UNMOUNT_ATTEMPTS))
done

echo "Compressing to final DMG..."
hdiutil convert "$DMG_TEMP" -format UDZO -imagekey zlib-level=9 -o "$DMG_PATH"
rm -f "$DMG_TEMP"

echo ""
echo "DMG created successfully: ${DMG_PATH}"
