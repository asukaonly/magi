#!/usr/bin/env bash
# Post-build: sign sidecar resources inside the .app, optionally notarize, and re-package.
#
# Runs AFTER 'tauri build' has assembled the .app bundle.  Tauri's bundler
# signs only the main binary + .app wrapper, but Apple notarization requires
# ALL Mach-O binaries to carry valid signatures.  This script fills the gap
# by signing every Mach-O inside Contents/Resources/sidecar-dist/ and
# Contents/Resources/plugin-python/ when present, then
# re-signing the .app, notarizing when credentials are available, and
# regenerating the DMG and updater archive so tauri-action uploads the final
# artifacts.
#
# Usage: ./scripts/sign-and-notarize-macos.sh <target-triple>
#
# Optional env vars:
#   APPLE_SIGNING_IDENTITY
#   APPLE_CERTIFICATE            (needed if identity not yet in keychain)
#   APPLE_CERTIFICATE_PASSWORD
#   APPLE_ID
#   APPLE_PASSWORD
#   APPLE_TEAM_ID
#   TAURI_SIGNING_PRIVATE_KEY            (for updater artifact re-signing)
#   TAURI_SIGNING_PRIVATE_KEY_PASSWORD   (for updater artifact re-signing)
set -euo pipefail

TARGET="${1:?Usage: $0 <target-triple>}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENTITLEMENTS="${ROOT_DIR}/scripts/sidecar.entitlements.plist"
RUNTIME_SIGNER="${ROOT_DIR}/scripts/sign-runtime-root-macos.sh"

# ── Locate build artifacts ──────────────────────────────────────
BUNDLE_DIR="${ROOT_DIR}/target/${TARGET}/release/bundle"
MACOS_DIR="${BUNDLE_DIR}/macos"
DMG_DIR="${BUNDLE_DIR}/dmg"

APP_PATH=$(find "$MACOS_DIR" -maxdepth 1 -name "*.app" -type d | head -1)
if [[ -z "$APP_PATH" ]]; then
  echo "ERROR: No .app found in ${MACOS_DIR}"
  exit 1
fi
APP_NAME=$(basename "$APP_PATH" .app)
echo "==> Found app: ${APP_PATH}"

SIDECAR="${APP_PATH}/Contents/Resources/sidecar-dist"
if [[ ! -d "$SIDECAR" ]]; then
  echo "ERROR: sidecar-dist not found inside .app bundle"
  exit 1
fi
PLUGIN_PYTHON="${APP_PATH}/Contents/Resources/plugin-python"

if [[ -z "${APPLE_SIGNING_IDENTITY:-}" ]]; then
  echo "WARNING: APPLE_SIGNING_IDENTITY is not set; skipping macOS sidecar signing and notarization."
  exit 0
fi

# ── Ensure signing identity is available ────────────────────────
# Tauri already imported the certificate for its own .app signing.
# Verify it's accessible; if not, import it ourselves.
if ! security find-identity -v -p codesigning 2>/dev/null \
     | grep -qF "${APPLE_SIGNING_IDENTITY}"; then
  echo "==> Signing identity not in keychain — importing certificate ..."
  if [[ -z "${APPLE_CERTIFICATE:-}" || -z "${APPLE_CERTIFICATE_PASSWORD:-}" ]]; then
    echo "ERROR: APPLE_CERTIFICATE and APPLE_CERTIFICATE_PASSWORD are required to import the signing identity."
    exit 1
  fi

  KEYCHAIN_PATH="${RUNNER_TEMP:-/tmp}/notarize-signing.keychain-db"
  KEYCHAIN_PASSWORD="$(openssl rand -hex 32)"

  security create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
  security set-keychain-settings -lut 21600 "$KEYCHAIN_PATH"
  security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"

  CERT_PATH="${RUNNER_TEMP:-/tmp}/notarize-cert.p12"
  echo "${APPLE_CERTIFICATE}" | base64 --decode > "$CERT_PATH"
  security import "$CERT_PATH" -P "${APPLE_CERTIFICATE_PASSWORD}" \
    -A -t cert -f pkcs12 -k "$KEYCHAIN_PATH"
  rm -f "$CERT_PATH"

  security set-key-partition-list -S apple-tool:,apple: \
    -s -k "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
  security list-keychains -d user -s "$KEYCHAIN_PATH" \
    $(security list-keychains -d user | xargs)
fi
echo "==> Signing identity ready."

# ── Debug: dump initial structure ───────────────────────────────
echo "==> Sidecar in .app (before processing):"
find "${SIDECAR}" -maxdepth 4 2>/dev/null | head -80 || true
echo "---"

# ── Remove stale _CodeSignature dirs ───────────────────────────
echo "==> Removing stale _CodeSignature dirs ..."
find "${SIDECAR}" -type d -name "_CodeSignature" -print \
  -exec rm -rf {} + 2>/dev/null || true

# ── Break hardlinks ─────────────────────────────────────────────
echo "==> Breaking hardlinks ..."
BROKEN=0
while IFS= read -r -d '' f; do
  [[ -L "$f" ]] && continue
  NLINKS=$(stat -f '%l' "$f")
  if [[ "$NLINKS" -gt 1 ]] && file "$f" | grep -q "Mach-O"; then
    TMP="${f}.__break__"
    cp "$f" "$TMP"
    mv "$TMP" "$f"
    BROKEN=$((BROKEN + 1))
    echo "  broke: ${f#"${SIDECAR}/"} (was ${NLINKS} links)"
  fi
done < <(find "${SIDECAR}" -type f -print0)
echo "    Broke ${BROKEN} hardlink(s)."

# ── Defuse .framework directories ──────────────────────────────
# Apple notarization treats *.framework as a framework bundle and
# demands proper Info.plist + Versions/ structure.  PyInstaller's
# Python.framework is non-standard and cannot be fixed reliably.
# Rename *.framework → *_framework and patch Mach-O load commands.
echo "==> Defusing .framework directories ..."
FW_OLD_BASES=()
FW_NEW_BASES=()

while IFS= read -r fw; do
  [[ -z "$fw" ]] && continue
  old_base=$(basename "$fw")
  stem="${old_base%.framework}"
  new_base="${stem}_framework"
  parent=$(dirname "$fw")

  echo "  rename: ${old_base} -> ${new_base}"
  mv "${parent}/${old_base}" "${parent}/${new_base}"
  FW_OLD_BASES+=("${old_base}")
  FW_NEW_BASES+=("${new_base}")
done < <(find "${SIDECAR}" -type d -name "*.framework" \
  | awk -F/ '{print NF, $0}' | sort -rn | cut -d' ' -f2-)

if [[ ${#FW_OLD_BASES[@]} -gt 0 ]]; then
  echo "==> Patching Mach-O load commands ..."
  while IFS= read -r -d '' f; do
    [[ -L "$f" ]] && continue
    file "$f" | grep -q "Mach-O" || continue

    for idx in "${!FW_OLD_BASES[@]}"; do
      old="${FW_OLD_BASES[$idx]}"
      new="${FW_NEW_BASES[$idx]}"

      # LC_LOAD_DYLIB / LC_LOAD_WEAK_DYLIB
      while IFS= read -r dep; do
        [[ -z "$dep" ]] && continue
        patched="${dep//${old}/${new}}"
        if [[ "$dep" != "$patched" ]]; then
          install_name_tool -change "$dep" "$patched" "$f" 2>/dev/null || true
        fi
      done < <(otool -L "$f" 2>/dev/null | awk '{print $1}' | grep "${old}" || true)

      # LC_ID_DYLIB
      cur_id=$(otool -D "$f" 2>/dev/null | tail -1)
      if [[ -n "$cur_id" && "$cur_id" == *"${old}"* ]]; then
        new_id="${cur_id//${old}/${new}}"
        install_name_tool -id "$new_id" "$f" 2>/dev/null || true
      fi

      # LC_RPATH
      while IFS= read -r rp; do
        [[ -z "$rp" ]] && continue
        patched="${rp//${old}/${new}}"
        if [[ "$rp" != "$patched" ]]; then
          install_name_tool -rpath "$rp" "$patched" "$f" 2>/dev/null || true
        fi
      done < <(otool -l "$f" 2>/dev/null \
        | awk '/cmd LC_RPATH/{found=1} found && /path /{print $2; found=0}' \
        | grep "${old}" || true)
    done
  done < <(find "${SIDECAR}" -type f -print0)

  # Retarget symlinks referencing the old framework name
  echo "==> Fixing symlinks ..."
  FIXED=0
  while IFS= read -r -d '' lnk; do
    target=$(readlink "$lnk")
    new_target="$target"
    for idx in "${!FW_OLD_BASES[@]}"; do
      new_target="${new_target//${FW_OLD_BASES[$idx]}/${FW_NEW_BASES[$idx]}}"
    done
    if [[ "$target" != "$new_target" ]]; then
      ln -sfn "$new_target" "$lnk"
      FIXED=$((FIXED + 1))
    fi
  done < <(find "${SIDECAR}" -type l -print0)
  echo "    Fixed ${FIXED} symlink(s)."

  # Remove remaining dangling symlinks
  while IFS= read -r -d '' lnk; do
    if [[ ! -e "$lnk" ]]; then
      echo "  removing dangling: ${lnk#"${SIDECAR}/"}"
      rm -f "$lnk"
    fi
  done < <(find "${SIDECAR}" -type l -print0)
fi

remaining=$(find "${SIDECAR}" -type d -name "*.framework" 2>/dev/null || true)
if [[ -n "$remaining" ]]; then
  echo "ERROR: .framework dirs still present: ${remaining}"
  exit 1
fi
echo "    Defused ${#FW_OLD_BASES[@]} framework(s)."

# ── Debug: post-defuse structure ────────────────────────────────
echo "==> Sidecar in .app (after processing):"
find "${SIDECAR}" -maxdepth 4 2>/dev/null | head -80 || true
echo "---"

# ── Sign all Mach-O in sidecar resources ────────────────────────
echo "==> Collecting Mach-O files ..."
ALL_MACHO=()
while IFS= read -r -d '' f; do
  [[ -L "$f" ]] && continue
  if file "$f" | grep -q "Mach-O"; then
    ALL_MACHO+=("$f")
  fi
done < <(find "${SIDECAR}" -type f -print0)

# Sort deepest paths first (leaf-first signing)
IFS=$'\n' SORTED=($(printf '%s\n' "${ALL_MACHO[@]}" \
  | awk -F/ '{print NF, $0}' | sort -rn | cut -d' ' -f2-))
unset IFS

TOTAL=${#SORTED[@]}
echo "==> Signing ${TOTAL} Mach-O files in sidecar ..."

COUNT=0
for f in "${SORTED[@]}"; do
  COUNT=$((COUNT + 1))
  echo "  [${COUNT}/${TOTAL}] ${f#"${SIDECAR}/"}"
  case "$f" in
    *.so|*.dylib)
      codesign --force --options runtime \
        --sign "${APPLE_SIGNING_IDENTITY}" --timestamp "$f"
      ;;
    *)
      codesign --force --options runtime \
        --sign "${APPLE_SIGNING_IDENTITY}" \
        --entitlements "${ENTITLEMENTS}" --timestamp "$f"
      ;;
  esac
done

# ── Verify sidecar signatures ──────────────────────────────────
echo "==> Verifying sidecar signatures ..."
FAIL=0
for f in "${SORTED[@]}"; do
  if ! codesign --verify --strict "$f" 2>/dev/null; then
    echo "  FAIL: ${f#"${SIDECAR}/"}"
    codesign -dvvv "$f" 2>&1 | head -5 || true
    FAIL=$((FAIL + 1))
  fi
done
if [[ $FAIL -gt 0 ]]; then
  echo "ERROR: ${FAIL} file(s) failed signature verification!"
  exit 1
fi
echo "    All ${TOTAL} sidecar signatures valid."

if [[ -d "${PLUGIN_PYTHON}" ]]; then
  bash "${RUNTIME_SIGNER}" "${PLUGIN_PYTHON}" "${ENTITLEMENTS}" "plugin-python"
else
  echo "WARNING: plugin-python not found inside .app bundle; skipping plugin Python signing."
fi

# ── Re-sign .app ────────────────────────────────────────────────
# We modified resources, so the .app's CodeResources hash is stale.
echo "==> Re-signing .app bundle ..."
MAIN_BIN=$(find "${APP_PATH}/Contents/MacOS" -type f | head -1)
if [[ -n "$MAIN_BIN" ]]; then
  codesign --force --options runtime \
    --sign "${APPLE_SIGNING_IDENTITY}" \
    --entitlements "${ENTITLEMENTS}" --timestamp "$MAIN_BIN"
fi

codesign --force --options runtime \
  --sign "${APPLE_SIGNING_IDENTITY}" \
  --entitlements "${ENTITLEMENTS}" --timestamp "${APP_PATH}"

echo "==> Verifying .app signature ..."
codesign --verify --deep --strict "${APP_PATH}"

# ── Notarize ────────────────────────────────────────────────────
if [[ -n "${APPLE_ID:-}" && -n "${APPLE_PASSWORD:-}" && -n "${APPLE_TEAM_ID:-}" ]]; then
  echo "==> Creating notarization zip ..."
  NOTARIZE_ZIP="${RUNNER_TEMP:-/tmp}/${APP_NAME}-notarize.zip"
  ditto -c -k --keepParent "${APP_PATH}" "${NOTARIZE_ZIP}"

  echo "==> Submitting to Apple notarization service ..."
  xcrun notarytool submit "${NOTARIZE_ZIP}" \
    --apple-id "${APPLE_ID}" \
    --password "${APPLE_PASSWORD}" \
    --team-id "${APPLE_TEAM_ID}" \
    --wait --timeout 30m

  echo "==> Stapling notarization ticket ..."
  xcrun stapler staple "${APP_PATH}"
  rm -f "${NOTARIZE_ZIP}"
else
  echo "WARNING: Apple notarization credentials are incomplete; skipping notarization."
fi

# ── Re-package DMG ──────────────────────────────────────────────
echo "==> Re-creating DMG ..."
OLD_DMG=$(find "${DMG_DIR}" -name "*.dmg" -type f 2>/dev/null | head -1)
if [[ -n "$OLD_DMG" ]]; then
  DMG_NAME=$(basename "$OLD_DMG")
  DMG_STAGING="$(mktemp -d "${RUNNER_TEMP:-/tmp}/magi-dmg-staging.XXXXXX")"
  trap 'rm -rf "${DMG_STAGING:-}"' EXIT

  rm -f "$OLD_DMG"
  cp -a "${APP_PATH}" "${DMG_STAGING}/"
  ln -s /Applications "${DMG_STAGING}/Applications"

  hdiutil create -volname "${APP_NAME}" \
    -srcfolder "${DMG_STAGING}" \
    -ov -format UDZO \
    "${DMG_DIR}/${DMG_NAME}"

  rm -rf "${DMG_STAGING}"
  trap - EXIT

  codesign --force --sign "${APPLE_SIGNING_IDENTITY}" \
    --timestamp "${DMG_DIR}/${DMG_NAME}"

  echo "    Created: ${DMG_NAME}"
else
  echo "    WARNING: No existing DMG found to re-create"
fi

# ── Re-package updater archive ──────────────────────────────────
echo "==> Re-creating updater archive ..."
OLD_TARGZ=$(find "${MACOS_DIR}" -name "*.app.tar.gz" ! -name "*.sig" \
  -type f 2>/dev/null | head -1)
if [[ -n "$OLD_TARGZ" ]]; then
  TARGZ_NAME=$(basename "$OLD_TARGZ")
  rm -f "$OLD_TARGZ" "${OLD_TARGZ}.sig"

  APP_BASENAME=$(basename "${APP_PATH}")
  (cd "${MACOS_DIR}" && tar czf "${TARGZ_NAME}" "${APP_BASENAME}")

  # Re-sign for Tauri updater
  if [[ -n "${TAURI_SIGNING_PRIVATE_KEY:-}" ]]; then
    (cd "${ROOT_DIR}/frontend" && npx tauri signer sign \
      --private-key "${TAURI_SIGNING_PRIVATE_KEY}" \
      --password "${TAURI_SIGNING_PRIVATE_KEY_PASSWORD:-}" \
      "${MACOS_DIR}/${TARGZ_NAME}")
    echo "    Created: ${TARGZ_NAME} + .sig"
  else
    echo "    WARNING: TAURI_SIGNING_PRIVATE_KEY not set, skipping updater signature"
  fi
else
  echo "    WARNING: No existing tar.gz found to re-create"
fi

echo "==> Sign and notarize complete!"
