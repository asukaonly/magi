#!/usr/bin/env bash
# Print "ready" only when both checked packages can still be downloaded from this run.
set -euo pipefail
gh api "repos/{owner}/{repo}/actions/runs/${1:?Missing CI run ID}/artifacts?per_page=100" --jq '
  [.artifacts[] | select(.expired == false) | .name] as $names |
  if (["desktop-aarch64-apple-darwin", "desktop-x86_64-pc-windows-msvc"] - $names | length) == 0
  then "ready" else "missing" end'
