#!/usr/bin/env bash
# Sign all Mach-O binaries in sidecar-dist for Apple notarization.
#
# Required env vars for signing:
#   APPLE_SIGNING_IDENTITY  – e.g. "Developer ID Application: ..."
#   APPLE_CERTIFICATE       – base64-encoded .p12 certificate
#   APPLE_CERTIFICATE_PASSWORD – password for the .p12 file
#
# Exits gracefully (exit 0) when identity/cert vars are missing (local dev).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SIDECAR_DIR="${ROOT_DIR}/frontend/src-tauri/sidecar-dist"
ENTITLEMENTS="${ROOT_DIR}/scripts/sidecar.entitlements.plist"

if [[ -z "${APPLE_SIGNING_IDENTITY:-}" ]]; then
  echo "APPLE_SIGNING_IDENTITY not set; skipping sidecar signing."
  exit 0
fi

if [[ -z "${APPLE_CERTIFICATE:-}" || -z "${APPLE_CERTIFICATE_PASSWORD:-}" ]]; then
  echo "APPLE_CERTIFICATE or APPLE_CERTIFICATE_PASSWORD not set; skipping."
  exit 0
fi

if [[ ! -d "${SIDECAR_DIR}" ]]; then
  echo "Error: sidecar-dist not found at ${SIDECAR_DIR}"
  exit 1
fi

# ── Keychain setup ──────────────────────────────────────────────
KEYCHAIN_PATH="${RUNNER_TEMP:-/tmp}/sidecar-signing.keychain-db"
KEYCHAIN_PASSWORD="$(openssl rand -hex 32)"

echo "==> Creating temporary keychain for sidecar signing ..."
security create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
security set-keychain-settings -lut 21600 "$KEYCHAIN_PATH"
security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"

CERT_PATH="${RUNNER_TEMP:-/tmp}/sidecar-cert.p12"
echo "$APPLE_CERTIFICATE" | base64 --decode > "$CERT_PATH"
security import "$CERT_PATH" \
  -P "$APPLE_CERTIFICATE_PASSWORD" \
  -A -t cert -f pkcs12 -k "$KEYCHAIN_PATH"
rm -f "$CERT_PATH"

security set-key-partition-list -S apple-tool:,apple: \
  -s -k "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
# Prepend our keychain while keeping existing ones in the search list
security list-keychains -d user -s "$KEYCHAIN_PATH" \
  $(security list-keychains -d user | xargs)

echo "==> Keychain ready."

# ── Collect Mach-O binaries ────────────────────────────────────
echo "==> Collecting Mach-O binaries in sidecar-dist ..."
LIBS=()
EXECS=()
while IFS= read -r -d '' f; do
  if file "$f" | grep -q "Mach-O"; then
    case "$f" in
      *.so|*.dylib) LIBS+=("$f") ;;
      *)            EXECS+=("$f") ;;
    esac
  fi
done < <(find "${SIDECAR_DIR}" -type f -print0)

TOTAL=$(( ${#LIBS[@]} + ${#EXECS[@]} ))
echo "==> Found ${TOTAL} Mach-O binaries (${#LIBS[@]} libraries, ${#EXECS[@]} executables)"

COUNT=0

# Sign shared libraries first (no entitlements needed)
for f in "${LIBS[@]}"; do
  COUNT=$((COUNT + 1))
  echo "  [${COUNT}/${TOTAL}] ${f#"${SIDECAR_DIR}/"}"
  codesign --force --options runtime \
    --sign "${APPLE_SIGNING_IDENTITY}" --timestamp "$f"
done

# Sign executables with entitlements (hardened runtime compatibility)
for f in "${EXECS[@]}"; do
  COUNT=$((COUNT + 1))
  echo "  [${COUNT}/${TOTAL}] ${f#"${SIDECAR_DIR}/"}"
  codesign --force --options runtime \
    --sign "${APPLE_SIGNING_IDENTITY}" \
    --entitlements "${ENTITLEMENTS}" --timestamp "$f"
done

echo "==> Sidecar signing complete (${TOTAL} binaries)."
