#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR/backend"

export PYTHONPATH="$ROOT_DIR/backend/src:$ROOT_DIR/sdk/src${PYTHONPATH:+:$PYTHONPATH}"

pytest \
  tests/transport/test_http_app.py \
  tests/transport/test_http_middleware.py \
  tests/runtime/test_tauri_dev_backend_lifecycle.py \
  tests/tools/test_feature_gating.py \
  -q
