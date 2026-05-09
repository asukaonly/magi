#!/usr/bin/env bash
# Sign all Mach-O binaries in a bundled runtime resource directory.
set -euo pipefail

RUNTIME_ROOT="${1:?Usage: $0 <runtime-root> <entitlements-plist> [label]}"
ENTITLEMENTS="${2:?Usage: $0 <runtime-root> <entitlements-plist> [label]}"
LABEL="${3:-$(basename "${RUNTIME_ROOT}")}"

if [[ -z "${APPLE_SIGNING_IDENTITY:-}" ]]; then
  echo "APPLE_SIGNING_IDENTITY not set; cannot sign ${LABEL}."
  exit 1
fi

if [[ ! -d "${RUNTIME_ROOT}" ]]; then
  echo "ERROR: ${LABEL} runtime root not found at ${RUNTIME_ROOT}"
  exit 1
fi

rel_path() {
  local path="$1"
  echo "${path#"${RUNTIME_ROOT}/"}"
}

echo "==> ${LABEL} structure (before processing):"
find "${RUNTIME_ROOT}" -maxdepth 4 2>/dev/null | head -80 || true
echo "---"

echo "==> Removing stale _CodeSignature dirs in ${LABEL} ..."
find "${RUNTIME_ROOT}" -type d -name "_CodeSignature" -print -exec rm -rf {} + 2>/dev/null || true

echo "==> Breaking hardlinks in ${LABEL} ..."
BROKEN=0
while IFS= read -r -d '' f; do
  [[ -L "$f" ]] && continue
  NLINKS=$(stat -f '%l' "$f")
  if [[ "$NLINKS" -gt 1 ]] && file "$f" | grep -q "Mach-O"; then
    TMP="${f}.__break__"
    cp "$f" "$TMP"
    mv "$TMP" "$f"
    BROKEN=$((BROKEN + 1))
    echo "  broke: $(rel_path "$f") (was ${NLINKS} links)"
  fi
done < <(find "${RUNTIME_ROOT}" -type f -print0)
echo "    Broke ${BROKEN} hardlink(s)."

echo "==> Defusing .framework directories in ${LABEL} ..."
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
done < <(find "${RUNTIME_ROOT}" -type d -name "*.framework" \
  | awk -F/ '{print NF, $0}' | sort -rn | cut -d' ' -f2-)

if [[ ${#FW_OLD_BASES[@]} -gt 0 ]]; then
  echo "==> Patching Mach-O load commands in ${LABEL} ..."
  while IFS= read -r -d '' f; do
    [[ -L "$f" ]] && continue
    file "$f" | grep -q "Mach-O" || continue

    for idx in "${!FW_OLD_BASES[@]}"; do
      old="${FW_OLD_BASES[$idx]}"
      new="${FW_NEW_BASES[$idx]}"

      while IFS= read -r dep; do
        [[ -z "$dep" ]] && continue
        patched="${dep//${old}/${new}}"
        if [[ "$dep" != "$patched" ]]; then
          install_name_tool -change "$dep" "$patched" "$f" 2>/dev/null || true
          echo "    load: $(rel_path "$f")"
        fi
      done < <(otool -L "$f" 2>/dev/null | awk '{print $1}' | grep "${old}" || true)

      cur_id=$(otool -D "$f" 2>/dev/null | tail -1)
      if [[ -n "$cur_id" && "$cur_id" == *"${old}"* ]]; then
        new_id="${cur_id//${old}/${new}}"
        install_name_tool -id "$new_id" "$f" 2>/dev/null || true
        echo "    id:   $(rel_path "$f")"
      fi

      while IFS= read -r rp; do
        [[ -z "$rp" ]] && continue
        patched="${rp//${old}/${new}}"
        if [[ "$rp" != "$patched" ]]; then
          install_name_tool -rpath "$rp" "$patched" "$f" 2>/dev/null || true
          echo "    rpath: $(rel_path "$f")"
        fi
      done < <(otool -l "$f" 2>/dev/null \
        | awk '/cmd LC_RPATH/{found=1} found && /path /{print $2; found=0}' \
        | grep "${old}" || true)
    done
  done < <(find "${RUNTIME_ROOT}" -type f -print0)

  echo "==> Fixing symlinks after framework rename in ${LABEL} ..."
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
      echo "  relink: $(rel_path "$lnk") -> ${new_target}"
    fi
  done < <(find "${RUNTIME_ROOT}" -type l -print0)
  echo "    Fixed ${FIXED_LINKS} symlink(s)."

  echo "==> Replacing dangling symlinks with copies in ${LABEL} ..."
  REPLACED=0
  while IFS= read -r -d '' lnk; do
    if [[ ! -e "$lnk" ]]; then
      echo "  WARNING: dangling symlink: $(rel_path "$lnk") -> $(readlink "$lnk")"
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
        echo "    replaced with copy from: $(rel_path "$resolved")"
      else
        echo "    ERROR: cannot resolve dangling symlink, removing"
        rm -f "$lnk"
      fi
    fi
  done < <(find "${RUNTIME_ROOT}" -type l -print0)
  echo "    Replaced ${REPLACED} dangling symlink(s)."
fi

remaining=$(find "${RUNTIME_ROOT}" -type d -name "*.framework" 2>/dev/null || true)
if [[ -n "$remaining" ]]; then
  echo "ERROR: .framework directories still present after defuse:"
  echo "$remaining"
  exit 1
fi
echo "    Defused ${#FW_OLD_BASES[@]} framework(s)."

echo "==> ${LABEL} structure (after defuse):"
find "${RUNTIME_ROOT}" -maxdepth 4 2>/dev/null | head -80 || true
echo "---"

echo "==> Collecting Mach-O files in ${LABEL} ..."
ALL_MACHO=()
while IFS= read -r -d '' f; do
  [[ -L "$f" ]] && continue
  if file "$f" | grep -q "Mach-O"; then
    ALL_MACHO+=("$f")
  fi
done < <(find "${RUNTIME_ROOT}" -type f -print0)

IFS=$'\n' SORTED=($(printf '%s\n' "${ALL_MACHO[@]}" \
  | awk -F/ '{print NF, $0}' | sort -rn | cut -d' ' -f2-))
unset IFS

TOTAL=${#SORTED[@]}
echo "==> Signing ${TOTAL} Mach-O files in ${LABEL} ..."

COUNT=0
for f in "${SORTED[@]}"; do
  COUNT=$((COUNT + 1))
  echo "  [${COUNT}/${TOTAL}] $(rel_path "$f")"

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

echo "==> Verifying ${LABEL} signatures ..."
FAIL=0
for f in "${SORTED[@]}"; do
  if ! codesign --verify --strict "$f" 2>/dev/null; then
    echo "  FAIL: $(rel_path "$f")"
    codesign -dvvv "$f" 2>&1 | head -5 || true
    FAIL=$((FAIL + 1))
  fi
done

if [[ $FAIL -gt 0 ]]; then
  echo "ERROR: ${FAIL} ${LABEL} file(s) failed signature verification!"
  exit 1
fi

echo "==> All ${TOTAL} ${LABEL} signatures verified."