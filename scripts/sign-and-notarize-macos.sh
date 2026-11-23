#!/usr/bin/env bash
# Sign the nested runtimes, notarize the desktop app, then create both delivery formats.
set -euo pipefail

TARGET="${1:?Usage: $0 <target-triple>}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENTITLEMENTS="${ROOT_DIR}/scripts/sidecar.entitlements.plist"
RUNTIME_SIGNER="${ROOT_DIR}/scripts/sign-runtime-root-macos.sh"

detach_stale_dmg_mounts() {
  local volume_path="/Volumes/${APP_NAME}"
  local found_mount=0

  while IFS= read -r mounted_path; do
    [[ -z "$mounted_path" ]] && continue
    found_mount=1
    echo "==> Detaching stale mounted volume ${mounted_path} ..."
    hdiutil detach "$mounted_path" -force || true
  done < <(mount | awk -v volume_path="$volume_path" '$3 == volume_path { print $3 }')

  if [[ $found_mount -eq 0 ]]; then
    echo "==> No stale mounted volume found for ${volume_path}"
  fi

  if [[ -d "$volume_path" ]] \
    && ! mount | awk -v volume_path="$volume_path" '$3 == volume_path { found=1 } END { exit found ? 0 : 1 }'; then
    rmdir "$volume_path" 2>/dev/null || true
  fi
}

create_dmg_with_retry() {
  local source_folder="$1"
  local output_path="$2"
  local max_attempts=5
  local attempt=1
  local exit_code=1

  while (( attempt <= max_attempts )); do
    detach_stale_dmg_mounts
    rm -f "$output_path" 2>/dev/null || true

    echo "==> Creating DMG (attempt ${attempt}/${max_attempts}) ..."
    if hdiutil create -volname "${APP_NAME}" \
      -srcfolder "${source_folder}" \
      -ov -format UDZO \
      "$output_path"; then
      return 0
    else
      exit_code=$?
    fi

    if (( attempt == max_attempts )); then
      break
    fi

    echo "WARNING: hdiutil create failed with exit code ${exit_code}; retrying after disk image cleanup ..."
    sleep $((attempt * 2))
    attempt=$((attempt + 1))
  done

  echo "ERROR: Failed to create DMG after ${max_attempts} attempts."
  return "$exit_code"
}

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

SIDECAR="${APP_PATH}/Contents/Resources/server-dist/sidecar-dist"
if [[ ! -d "$SIDECAR" ]]; then
  echo "ERROR: sidecar-dist not found inside .app bundle"
  exit 1
fi
PLUGIN_PYTHON="${APP_PATH}/Contents/Resources/server-dist/plugin-python"

: "${APPLE_SIGNING_IDENTITY:?Missing desktop signing identity}"
: "${APPLE_ID:?Missing Apple notarization account}"
: "${APPLE_PASSWORD:?Missing Apple notarization password}"
: "${APPLE_TEAM_ID:?Missing Apple team ID}"
: "${TAURI_SIGNING_PRIVATE_KEY:?Missing updater signing key}"

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

bash "${RUNTIME_SIGNER}" "${SIDECAR}" "${ENTITLEMENTS}" sidecar
bash "${RUNTIME_SIGNER}" "${PLUGIN_PYTHON}" "${ENTITLEMENTS}" plugin-python
codesign --force --options runtime --sign "${APPLE_SIGNING_IDENTITY}" --timestamp "${APP_PATH}/Contents/Resources/server-dist/magi-server"


desktop_entitlements="${ROOT_DIR}/frontend/src-tauri/Entitlements.plist"
codesign --force --options runtime --sign "${APPLE_SIGNING_IDENTITY}" \
  --entitlements "${desktop_entitlements}" --timestamp "${APP_PATH}"
codesign --verify --deep --strict "${APP_PATH}"
codesign -d --xml --entitlements - "${APP_PATH}" | python3 -c '
import plistlib, sys
from pathlib import Path
expected = plistlib.loads(Path(sys.argv[1]).read_bytes())
if plistlib.loads(sys.stdin.buffer.read()) != expected:
    sys.exit("Signed desktop entitlements differ from Entitlements.plist")
' "${desktop_entitlements}"

staging="$(mktemp -d "${RUNNER_TEMP:-/tmp}/magi-desktop.XXXXXX")"
trap 'rm -rf "$staging"' EXIT
ditto -c -k --keepParent "${APP_PATH}" "${staging}/notarize.zip"
xcrun notarytool submit "${staging}/notarize.zip" --apple-id "${APPLE_ID}" \
  --password "${APPLE_PASSWORD}" --team-id "${APPLE_TEAM_ID}" --wait --timeout 30m
xcrun stapler staple "${APP_PATH}"
xcrun stapler validate "${APP_PATH}"

version="$(cat "${ROOT_DIR}/VERSION")"
dmg="${DMG_DIR}/${APP_NAME}_${version}_${TARGET%%-*}.dmg"
mkdir -p "${DMG_DIR}" "${staging}/image"
ditto "${APP_PATH}" "${staging}/image/${APP_NAME}.app"
ln -s /Applications "${staging}/image/Applications"
create_dmg_with_retry "${staging}/image" "${dmg}"
codesign --force --sign "${APPLE_SIGNING_IDENTITY}" --timestamp "${dmg}"

archive="${APP_PATH}.tar.gz"
tar -czf "${archive}" -C "${MACOS_DIR}" "${APP_NAME}.app"
(cd "${ROOT_DIR}/frontend" && npx --no-install tauri signer sign "${archive}")
test -s "${archive}.sig"
