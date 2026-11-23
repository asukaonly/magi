#!/usr/bin/env bash
# Emit NUL-delimited native file paths, preserving spaces and newlines in resource names.
set -euo pipefail
/usr/bin/find "${1:?Missing runtime directory}" -depth -type f -exec /usr/bin/file -E -r -00 {} + |
  while IFS= read -r -d '' item && IFS= read -r -d '' description; do
    if [[ "$description" == Mach-O* ]]; then printf '%s\0' "$item"; fi
  done
