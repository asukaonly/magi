#!/usr/bin/env bash
set -euo pipefail
COLLECTOR_PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COLLECTOR_DATA_DIR="${MAGI_COLLECTOR_DATA_DIR:-$HOME/.magi-collector-dev}"
cd "$COLLECTOR_PROJECT_ROOT"
exec cargo run -p magi-server -- --development-root "$COLLECTOR_PROJECT_ROOT" --data-dir "$COLLECTOR_DATA_DIR" collect "$@"
