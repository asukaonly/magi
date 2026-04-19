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

# ── Debug: dump initial sidecar structure ───────────────────────
echo "==> Sidecar structure (before processing):"
find "${SIDECAR_DIR}" -maxdepth 4 2>/dev/null | head -80 || true
echo "---"

# ── Pre-sign: remove stale code signatures ─────────────────────
echo "==> Removing stale _CodeSignature dirs ..."
find "${SIDECAR_DIR}" -type d -name "_CodeSignature" -print -exec rm -rf {} + 2>/dev/null || true

# ── Pre-sign: break hardlinks ──────────────────────────────────
# PyInstaller hardlinks _internal/Python to Python.framework/…/Python.
# Signing one hardlinked path mutates the shared inode, invalidating
# the other.  Replace hardlinks with independent copies.
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
    echo "  broke: ${f#"${SIDECAR_DIR}/"} (was ${NLINKS} links)"
  fi
done < <(find "${SIDECAR_DIR}" -type f -print0)
echo "    Broke ${BROKEN} hardlink(s)."

# ── Pre-sign: defuse .framework directories ────────────────────
# Apple notarization treats ANY directory named *.framework as a
# macOS framework bundle and requires:
#   - Info.plist with CFBundleExecutable
#   - Proper Versions/ symlink structure
#   - Valid bundle-level code signature
#
# PyInstaller ships a Python.framework that fails all of these.
# Previous attempts to normalize it into a valid bundle also failed,
# likely because Tauri's resource copy follows symlinks and destroys
# the carefully created bundle structure before notarization.
#
# Definitive fix: rename *.framework -> *_framework so Apple never
# treats it as a framework bundle.  Then patch all Mach-O load
# commands (LC_LOAD_DYLIB, LC_ID_DYLIB, LC_RPATH) to match.

echo "==> Defusing .framework directories ..."
FW_OLD_BASES=()
FW_NEW_BASES=()

# Process deepest first in case of nested frameworks
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
done < <(find "${SIDECAR_DIR}" -type d -name "*.framework" \
  | awk -F/ '{print NF, $0}' | sort -rn | cut -d' ' -f2-)

if [[ ${#FW_OLD_BASES[@]} -gt 0 ]]; then
  echo "==> Patching Mach-O load commands ..."
  while IFS= read -r -d '' f; do
    [[ -L "$f" ]] && continue
    file "$f" | grep -q "Mach-O" || continue

    for idx in "${!FW_OLD_BASES[@]}"; do
      old="${FW_OLD_BASES[$idx]}"
      new="${FW_NEW_BASES[$idx]}"

      # Patch LC_LOAD_DYLIB / LC_LOAD_WEAK_DYLIB
      while IFS= read -r dep; do
        [[ -z "$dep" ]] && continue
        patched="${dep//${old}/${new}}"
        if [[ "$dep" != "$patched" ]]; then
          install_name_tool -change "$dep" "$patched" "$f" 2>/dev/null || true
          echo "    load: ${f#"${SIDECAR_DIR}/"}"
        fi
      done < <(otool -L "$f" 2>/dev/null | awk '{print $1}' | grep "${old}" || true)

      # Patch LC_ID_DYLIB (library's own install name)
      cur_id=$(otool -D "$f" 2>/dev/null | tail -1)
      if [[ -n "$cur_id" && "$cur_id" == *"${old}"* ]]; then
        new_id="${cur_id//${old}/${new}}"
        install_name_tool -id "$new_id" "$f" 2>/dev/null || true
        echo "    id:   ${f#"${SIDECAR_DIR}/"}"
      fi

      # Patch LC_RPATH entries that reference the old name
      while IFS= read -r rp; do
        [[ -z "$rp" ]] && continue
        patched="${rp//${old}/${new}}"
        if [[ "$rp" != "$patched" ]]; then
          install_name_tool -rpath "$rp" "$patched" "$f" 2>/dev/null || true
          echo "    rpath: ${f#"${SIDECAR_DIR}/"}"
        fi
      done < <(otool -l "$f" 2>/dev/null \
        | awk '/cmd LC_RPATH/{found=1} found && /path /{print $2; found=0}' \
        | grep "${old}" || true)
    done
  done < <(find "${SIDECAR_DIR}" -type f -print0)

  # Fix symlinks whose targets referenced the old framework name.
  # e.g. _internal/Python -> Python.framework/Versions/3.11/Python
  # becomes dangling after the rename; retarget to Python_framework/…
  echo "==> Fixing symlinks after framework rename ..."
  FIXED_LINKS=0
  while IFS= read -r -d '' lnk; do
    target=$(readlink "$lnk")
    new_target="$target"
    for idx in "${!FW_OLD_BASES[@]}"; do
      new_target="${new_target//${FW_OLD_BASES[$idx]}/${FW_NEW_BASES[$idx]}}"
    done
    if [[ "$target" != "$new_target" ]]; then
      ln -sfn "$new_target" "$lnk"
      FIXED_LINKS=$((FIXED_LINKS + 1))
      echo "  relink: ${lnk#"${SIDECAR_DIR}/"} -> ${new_target}"
    fi
  done < <(find "${SIDECAR_DIR}" -type l -print0)
  echo "    Fixed ${FIXED_LINKS} symlink(s)."

  # Replace any remaining dangling symlinks with copies of their targets.
  # (Safety net in case symlinks cross framework boundaries.)
  echo "==> Replacing dangling symlinks with copies ..."
  REPLACED=0
  while IFS= read -r -d '' lnk; do
    if [[ ! -e "$lnk" ]]; then
      echo "  WARNING: dangling symlink: ${lnk#"${SIDECAR_DIR}/"} -> $(readlink "$lnk")"
      # Try to resolve by looking for the file under the new name
      resolved=""
      for idx in "${!FW_OLD_BASES[@]}"; do
        candidate="${lnk%/*}/$(readlink "$lnk" | sed "s/${FW_OLD_BASES[$idx]}/${FW_NEW_BASES[$idx]}/g")"
        if [[ -f "$candidate" ]]; then
          resolved="$candidate"
          break
        fi
      done
      if [[ -n "$resolved" ]]; then
        rm -f "$lnk"
        cp "$resolved" "$lnk"
        REPLACED=$((REPLACED + 1))
        echo "    replaced with copy from: ${resolved#"${SIDECAR_DIR}/"}"
      else
        echo "    ERROR: cannot resolve dangling symlink, removing"
        rm -f "$lnk"
      fi
    fi
  done < <(find "${SIDECAR_DIR}" -type l -print0)
  echo "    Replaced ${REPLACED} dangling symlink(s)."
fi

# Verify no .framework dirs remain
remaining=$(find "${SIDECAR_DIR}" -type d -name "*.framework" 2>/dev/null || true)
if [[ -n "$remaining" ]]; then
  echo "ERROR: .framework directories still present after defuse:"
  echo "$remaining"
  exit 1
fi
echo "    Defused ${#FW_OLD_BASES[@]} framework(s)."

# ── Debug: dump structure after defuse ──────────────────────────
echo "==> Sidecar structure (after defuse):"
find "${SIDECAR_DIR}" -maxdepth 4 2>/dev/null | head -80 || true
echo "---"

# ── Sign all Mach-O binaries ───────────────────────────────────
# No framework bundle signing needed — all .framework dirs have been
# renamed.  Sign every individual Mach-O file, deepest paths first.

echo "==> Collecting Mach-O files ..."
ALL_MACHO=()
while IFS= read -r -d '' f; do
  [[ -L "$f" ]] && continue
  if file "$f" | grep -q "Mach-O"; then
    ALL_MACHO+=("$f")
  fi
done < <(find "${SIDECAR_DIR}" -type f -print0)

IFS=$'\n' SORTED=($(printf '%s\n' "${ALL_MACHO[@]}" \
  | awk -F/ '{print NF, $0}' | sort -rn | cut -d' ' -f2-))
unset IFS

TOTAL=${#SORTED[@]}
echo "==> Signing ${TOTAL} Mach-O files ..."

COUNT=0
for f in "${SORTED[@]}"; do
  COUNT=$((COUNT + 1))
  REL="${f#"${SIDECAR_DIR}/"}"
  echo "  [${COUNT}/${TOTAL}] ${REL}"

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

# ── Verify all signatures ──────────────────────────────────────
echo "==> Verifying all signatures ..."
FAIL=0
for f in "${SORTED[@]}"; do
  if ! codesign --verify --strict "$f" 2>/dev/null; then
    echo "  FAIL: ${f#"${SIDECAR_DIR}/"}"
    codesign -dvvv "$f" 2>&1 | head -5 || true
    FAIL=$((FAIL + 1))
  fi
done

if [[ $FAIL -gt 0 ]]; then
  echo "ERROR: ${FAIL} file(s) failed signature verification!"
  exit 1
fi

echo "==> All ${TOTAL} signatures verified."
echo "==> Sidecar signing complete."
