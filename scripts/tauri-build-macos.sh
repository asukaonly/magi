#!/usr/bin/env bash
# Wrapper around `tauri` CLI for macOS builds.
#
# Used as tauriScript in tauri-action.  The action invokes:
#   <this-script> build --target <triple> [other args ...]
#
# Strategy:
#   1. Strip notarization env vars so `tauri build` signs the .app but
#      does NOT attempt notarization (which would fail on unsigned resources).
#   2. Run `npx tauri "$@"` (the normal build).
#   3. Restore notarization env vars.
#   4. Call sign-and-notarize-macos.sh to sign resources, notarize, and
#      re-package DMG + updater archive in-place.
#
# tauri-action then picks up the fully-notarized artifacts from the
# standard output paths and uploads them to the GitHub release.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Save all arguments before consumption
ARGS=("$@")

# ── Strip notarization vars ─────────────────────────────────────
# Tauri CLI checks APPLE_ID + APPLE_PASSWORD + APPLE_TEAM_ID to decide
# whether to notarize.  Unsetting them makes Tauri skip notarization.
SAVED_APPLE_ID="${APPLE_ID:-}"
SAVED_APPLE_PASSWORD="${APPLE_PASSWORD:-}"
SAVED_APPLE_TEAM_ID="${APPLE_TEAM_ID:-}"
unset APPLE_ID APPLE_PASSWORD APPLE_TEAM_ID

echo "==> [tauri-build-macos] Running tauri build (signing only, no notarization) ..."
npx tauri "${ARGS[@]}"

# ── Restore notarization vars ───────────────────────────────────
export APPLE_ID="$SAVED_APPLE_ID"
export APPLE_PASSWORD="$SAVED_APPLE_PASSWORD"
export APPLE_TEAM_ID="$SAVED_APPLE_TEAM_ID"

# ── Extract target triple from args ─────────────────────────────
TARGET=""
for ((i = 0; i < ${#ARGS[@]}; i++)); do
  if [[ "${ARGS[$i]}" == "--target" ]] && [[ $((i + 1)) -lt ${#ARGS[@]} ]]; then
    TARGET="${ARGS[$((i + 1))]}"
    break
  fi
done

if [[ -z "$TARGET" ]]; then
  echo "WARNING: Could not determine target triple from args; skipping notarization."
  exit 0
fi

# ── Sign resources and notarize ─────────────────────────────────
echo "==> [tauri-build-macos] Signing sidecar resources and notarizing ..."
"${SCRIPT_DIR}/sign-and-notarize-macos.sh" "$TARGET"
