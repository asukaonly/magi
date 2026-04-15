#!/usr/bin/env bash
# Sign all Mach-O binaries in sidecar-dist for Apple notarization.
# Requires APPLE_SIGNING_IDENTITY env var (e.g. "Developer ID Application: ...").
# Exits gracefully if APPLE_SIGNING_IDENTITY is unset (local dev builds).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SIDECAR_DIR="${ROOT_DIR}/frontend/src-tauri/sidecar-dist"
ENTITLEMENTS="${ROOT_DIR}/scripts/sidecar.entitlements.plist"

if [[ -z "${APPLE_SIGNING_IDENTITY:-}" ]]; then
  echo "APPLE_SIGNING_IDENTITY not set; skipping sidecar signing."
  exit 0
fi

if [[ ! -d "${SIDECAR_DIR}" ]]; then
  echo "Error: sidecar-dist not found at ${SIDECAR_DIR}"
  exit 1
fi

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
