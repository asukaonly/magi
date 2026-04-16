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
echo "==> Removing stale _CodeSignature dirs inside sidecar-dist ..."
find "${SIDECAR_DIR}" -type d -name "_CodeSignature" -print -exec rm -rf {} + 2>/dev/null || true

# Break hardlinks.  PyInstaller often hardlinks _internal/Python to
# Python.framework/Versions/*/Python.  Signing one hardlinked path
# mutates the shared inode and can invalidate the other's signature.
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

# ── Normalize .framework bundles ────────────────────────────────
# PyInstaller ships a non-standard Python.framework that lacks
# Info.plist and sometimes proper versioned symlinks.  Apple
# notarization rejects code inside directories ending in .framework
# unless the framework is a valid signed bundle.
#
# Strategy (方案 A): add the missing pieces so the framework becomes
# a proper bundle that codesign can handle natively.

normalize_framework() {
  local fw_path="$1"
  local fw_name
  fw_name=$(basename "$fw_path" .framework)

  echo "  Normalizing ${fw_path#"${SIDECAR_DIR}/"} ..."

  local versions_dir="${fw_path}/Versions"
  if [[ ! -d "${versions_dir}" ]]; then
    echo "    WARNING: no Versions/ dir – cannot normalize"
    return 1
  fi

  # Resolve the real version directory (follow Current symlink or pick first)
  local version_name=""
  if [[ -L "${versions_dir}/Current" ]]; then
    version_name=$(readlink "${versions_dir}/Current")
  else
    for d in "${versions_dir}"/*/; do
      local dn
      dn=$(basename "$d")
      [[ "$dn" == "Current" ]] && continue
      version_name="$dn"
      break
    done
  fi

  if [[ -z "$version_name" ]]; then
    echo "    WARNING: no version subdirectory found"
    return 1
  fi

  local version_dir="${versions_dir}/${version_name}"
  echo "    version: ${version_name}"

  # 1) Ensure Versions/Current symlink
  if [[ ! -L "${versions_dir}/Current" ]]; then
    ln -sf "${version_name}" "${versions_dir}/Current"
    echo "    + symlink Versions/Current -> ${version_name}"
  fi

  # 2) Create Resources/Info.plist when missing
  local resources_dir="${version_dir}/Resources"
  if [[ ! -f "${resources_dir}/Info.plist" ]]; then
    mkdir -p "$resources_dir"
    cat > "${resources_dir}/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key>
  <string>org.python.python</string>
  <key>CFBundleName</key>
  <string>${fw_name}</string>
  <key>CFBundleExecutable</key>
  <string>${fw_name}</string>
  <key>CFBundleVersion</key>
  <string>${version_name}</string>
  <key>CFBundleShortVersionString</key>
  <string>${version_name}</string>
  <key>CFBundlePackageType</key>
  <string>FMWK</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
</dict>
</plist>
PLIST
    echo "    + created Info.plist"
  fi

  # 3) Ensure top-level Resources symlink
  if [[ ! -e "${fw_path}/Resources" ]]; then
    ln -sf "Versions/Current/Resources" "${fw_path}/Resources"
    echo "    + symlink Resources -> Versions/Current/Resources"
  fi

  # 4) Main binary at top level must be a symlink, not a regular file.
  #    Hardlink-breaking may have turned it into a regular file.
  local top_bin="${fw_path}/${fw_name}"
  if [[ -f "$top_bin" && ! -L "$top_bin" ]]; then
    rm -f "$top_bin"
    ln -sf "Versions/Current/${fw_name}" "$top_bin"
    echo "    + replaced regular file ${fw_name} with symlink"
  elif [[ ! -e "$top_bin" ]]; then
    ln -sf "Versions/Current/${fw_name}" "$top_bin"
    echo "    + symlink ${fw_name} -> Versions/Current/${fw_name}"
  fi

  return 0
}

echo "==> Normalizing .framework bundles ..."
FRAMEWORKS=()
while IFS= read -r -d '' fw; do
  FRAMEWORKS+=("$fw")
done < <(find "${SIDECAR_DIR}" -type d -name "*.framework" -print0)

for fw in "${FRAMEWORKS[@]}"; do
  normalize_framework "$fw" || true
done
echo "==> Normalized ${#FRAMEWORKS[@]} framework(s)."

# ── Phase 1: Sign leaf libraries (.so / .dylib) everywhere ─────
echo "==> Phase 1/3: Signing shared libraries ..."
LIB_COUNT=0
while IFS= read -r -d '' f; do
  [[ -L "$f" ]] && continue
  if file "$f" | grep -q "Mach-O"; then
    echo "  lib: ${f#"${SIDECAR_DIR}/"}"
    codesign --force --options runtime \
      --sign "${APPLE_SIGNING_IDENTITY}" --timestamp "$f"
    LIB_COUNT=$((LIB_COUNT + 1))
  fi
done < <(find "${SIDECAR_DIR}" -type f \( -name "*.so" -o -name "*.dylib" \) -print0)
echo "    Signed ${LIB_COUNT} shared libraries."

# ── Phase 2: Sign .framework bundles ───────────────────────────
# Signing a framework bundle signs its main binary and creates
# _CodeSignature/CodeResources.  Inner .so/.dylib must already be
# signed (Phase 1).
echo "==> Phase 2/3: Signing .framework bundles ..."
for fw in "${FRAMEWORKS[@]}"; do
  echo "  bundle: ${fw#"${SIDECAR_DIR}/"}"
  codesign --force --options runtime \
    --sign "${APPLE_SIGNING_IDENTITY}" \
    --entitlements "${ENTITLEMENTS}" --timestamp "$fw"
done
echo "    Signed ${#FRAMEWORKS[@]} framework bundle(s)."

# ── Phase 3: Sign remaining Mach-O outside .framework ──────────
echo "==> Phase 3/3: Signing remaining executables ..."
EXEC_COUNT=0
while IFS= read -r -d '' f; do
  [[ -L "$f" ]] && continue
  # Skip .so/.dylib (already signed) and anything inside .framework/
  case "$f" in *.so|*.dylib) continue ;; esac
  case "$f" in *.framework/*) continue ;; esac
  if file "$f" | grep -q "Mach-O"; then
    echo "  exec: ${f#"${SIDECAR_DIR}/"}"
    codesign --force --options runtime \
      --sign "${APPLE_SIGNING_IDENTITY}" \
      --entitlements "${ENTITLEMENTS}" --timestamp "$f"
    EXEC_COUNT=$((EXEC_COUNT + 1))
  fi
done < <(find "${SIDECAR_DIR}" -type f -print0)
echo "    Signed ${EXEC_COUNT} executables."

TOTAL=$(( LIB_COUNT + ${#FRAMEWORKS[@]} + EXEC_COUNT ))
echo "==> Sidecar signing complete (${TOTAL} items)."
