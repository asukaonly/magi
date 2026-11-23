#!/usr/bin/env bash
# tauri-action calls this in frontend/ and discovers the signed artifacts afterwards.
set -euo pipefail
case "${MAGI_BUILD_TARGET:?Missing release target}" in
  aarch64-apple-darwin) exec ../scripts/sign-and-notarize-macos.sh "$MAGI_BUILD_TARGET" ;;
  x86_64-pc-windows-msvc)
    installer="../target/$MAGI_BUILD_TARGET/release/bundle/nsis/Magi_$(cat ../VERSION)_x64-setup.exe"
    npx --no-install tauri signer sign "$installer"
    test -s "$installer.sig"
    ;;
  *) echo "Unsupported desktop release target: $MAGI_BUILD_TARGET" >&2; exit 1 ;;
esac
