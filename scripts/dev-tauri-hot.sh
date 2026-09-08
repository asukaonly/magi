#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}/frontend"
# Service leases and parent pipes own lifecycle; never kill unrelated listeners or workers.
exec env VITE_DEV_SERVER_HOST=127.0.0.1 VITE_DEV_SERVER_PORT=5173 npm run tauri:dev
