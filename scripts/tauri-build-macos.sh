#!/usr/bin/env bash
# tauri-action discovers the final DMG and updater archive after this command returns.
set -euo pipefail
: "${MAGI_BUILD_TARGET:?Missing release target}"
(unset APPLE_ID APPLE_PASSWORD APPLE_TEAM_ID && npx --no-install tauri build \
  --target "${MAGI_BUILD_TARGET}" --bundles app --config '{"bundle":{"createUpdaterArtifacts":false}}')
exec "$(dirname "$0")/sign-and-notarize-macos.sh" "${MAGI_BUILD_TARGET}"
