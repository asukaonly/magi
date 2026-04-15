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

# ── Collect and sign ────────────────────────────────────────────
# Signing order matters for Apple notarization:
#   1. .so / .dylib shared libraries (leaf dependencies)
#   2. .framework bundles (signed as bundles, not individual files)
#   3. Executable binaries (top-level; with entitlements)
#
# Files inside .framework/ are skipped because signing the framework
# bundle covers them. Symlinks are also skipped.

echo "==> Phase 1: Signing shared libraries (.so / .dylib) ..."
LIBS=()
while IFS= read -r -d '' f; do
  # Skip anything inside a .framework bundle
  case "$f" in *.framework/*) continue ;; esac
  if file "$f" | grep -q "Mach-O"; then
    LIBS+=("$f")
  fi
done < <(find "${SIDECAR_DIR}" -type f \( -name "*.so" -o -name "*.dylib" \) -print0)

for f in "${LIBS[@]}"; do
  echo "  lib: ${f#"${SIDECAR_DIR}/"}"
  codesign --force --options runtime \
    --sign "${APPLE_SIGNING_IDENTITY}" --timestamp "$f"
done
echo "    Signed ${#LIBS[@]} shared libraries."

echo "==> Phase 2: Signing .framework bundles ..."
FRAMEWORKS=()
while IFS= read -r -d '' fw; do
  FRAMEWORKS+=("$fw")
done < <(find "${SIDECAR_DIR}" -type d -name "*.framework" -print0)

for fw in "${FRAMEWORKS[@]}"; do
  echo "  framework: ${fw#"${SIDECAR_DIR}/"}"
  codesign --force --options runtime \
    --sign "${APPLE_SIGNING_IDENTITY}" \
    --entitlements "${ENTITLEMENTS}" --timestamp "$fw"
done
echo "    Signed ${#FRAMEWORKS[@]} framework bundles."

echo "==> Phase 3: Signing remaining executables ..."
EXECS=()
while IFS= read -r -d '' f; do
  # Skip shared libs (already signed), framework contents, and symlinks
  case "$f" in *.so|*.dylib) continue ;; esac
  case "$f" in *.framework/*) continue ;; esac
  if file "$f" | grep -q "Mach-O"; then
    EXECS+=("$f")
  fi
done < <(find "${SIDECAR_DIR}" -type f -not -type l -print0)

for f in "${EXECS[@]}"; do
  echo "  exec: ${f#"${SIDECAR_DIR}/"}"
  codesign --force --options runtime \
    --sign "${APPLE_SIGNING_IDENTITY}" \
    --entitlements "${ENTITLEMENTS}" --timestamp "$f"
done
echo "    Signed ${#EXECS[@]} executables."

TOTAL=$(( ${#LIBS[@]} + ${#FRAMEWORKS[@]} + ${#EXECS[@]} ))
echo "==> Sidecar signing complete (${TOTAL} items)."
