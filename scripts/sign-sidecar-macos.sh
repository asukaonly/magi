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

# ── Pre-sign cleanup ────────────────────────────────────────────
# 1. Remove any stale _CodeSignature dirs inside .framework bundles
#    left by prior signing attempts or PyInstaller itself.
# 2. Break hardlinks.  PyInstaller often hardlinks _internal/Python
#    to Python.framework/Versions/*/Python.  Apple notarization may
#    reject signed binaries that share an inode, because re-signing
#    one path silently mutates the other.  Replacing hardlinks with
#    independent copies eliminates this class of failure.

echo "==> Removing stale _CodeSignature dirs inside sidecar-dist ..."
find "${SIDECAR_DIR}" -type d -name "_CodeSignature" -print -exec rm -rf {} + 2>/dev/null || true

echo "==> Breaking hardlinks for Mach-O files ..."
BROKEN=0
while IFS= read -r -d '' f; do
  [[ -L "$f" ]] && continue
  NLINKS=$(stat -f '%l' "$f")
  if [[ "$NLINKS" -gt 1 ]] && file "$f" | grep -q "Mach-O"; then
    TMPFILE="${f}.__break_hl__"
    cp "$f" "$TMPFILE"
    mv "$TMPFILE" "$f"
    BROKEN=$((BROKEN + 1))
    echo "  broke hardlink: ${f#"${SIDECAR_DIR}/"} (was ${NLINKS} links)"
  fi
done < <(find "${SIDECAR_DIR}" -type f -print0)
echo "==> Broke ${BROKEN} hardlinks."

# ── Collect and sign ────────────────────────────────────────────
# PyInstaller bundles a non-standard Python.framework that lacks
# Info.plist and proper versioned structure.  Signing it as a bundle
# produces an *invalid* signature.
#
# Strategy: sign every individual Mach-O file (including those inside
# .framework/ directories).  Sign deepest paths first so inner
# dependencies are signed before outer binaries.
#
# Symlinks (e.g. _internal/Python -> Python.framework/…/Python) are
# skipped; signing the real target is sufficient.

echo "==> Collecting all Mach-O files in sidecar-dist ..."
ALL_MACHO=()
while IFS= read -r -d '' f; do
  [[ -L "$f" ]] && continue
  if file "$f" | grep -q "Mach-O"; then
    ALL_MACHO+=("$f")
  fi
done < <(find "${SIDECAR_DIR}" -type f -print0)

# Sort by path depth descending so inner files are signed first
IFS=$'\n' SORTED=($(printf '%s\n' "${ALL_MACHO[@]}" | awk -F/ '{print NF, $0}' | sort -rn | cut -d' ' -f2-))
unset IFS

TOTAL=${#SORTED[@]}
echo "==> Found ${TOTAL} Mach-O files to sign."

COUNT=0
for f in "${SORTED[@]}"; do
  COUNT=$((COUNT + 1))
  REL="${f#"${SIDECAR_DIR}/"}"
  echo "  [${COUNT}/${TOTAL}] ${REL}"

  # Shared libraries: no entitlements needed
  # Executables (magi-backend, Python, node, etc.): need entitlements
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

echo "==> Sidecar signing complete (${TOTAL} files)."
