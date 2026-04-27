#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON:-python}"

cd "$ROOT_DIR/backend"

export PYTHONPATH="$ROOT_DIR/backend/src:$ROOT_DIR/sdk/src${PYTHONPATH:+:$PYTHONPATH}"

"$PYTHON_BIN" -m mypy \
  --config-file pyproject.toml \
  --follow-imports=skip \
  src/magi/llm/base.py \
  src/magi/llm/concurrency_limiter.py \
  src/magi/llm/streaming_events.py \
  src/magi/llm/usage_events.py \
  src/magi/llm/parsers/content_sanitizer.py \
  src/magi/llm/parsers/tool_call_parser.py \
  src/magi/memory/l2/ontology.py \
  src/magi/memory/l2/evidence_policy.py \
  src/magi/memory/l2/graph_conflicts.py \
  src/magi/memory/l2/maintenance_schedule.py
