#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON:-python}"

cd "$ROOT_DIR/backend/src"

export PYTHONPATH="$ROOT_DIR/backend/src:$ROOT_DIR/sdk/src${PYTHONPATH:+:$PYTHONPATH}"

TYPE_GATE_DIRS=(
  magi/agent/execution/function_calling
  magi/chat/task_agent/postprocess
  magi/agent/workers
  magi/llm/provider_bridge
  magi/llm/parsers
  magi/memory/l1/embeddings
  magi/memory/l1/entities
  magi/memory/l1/retrieval
  magi/memory/l1/storage
  magi/memory/l2/assertions
  magi/memory/l2/entities/catalog
  magi/memory/l2/entities/maintenance
  magi/memory/l2/extraction
  magi/memory/l2/governance
  magi/memory/l2/graph
  magi/memory/l2/pipeline/prompts
  magi/memory/l2/pipeline/validation
  magi/memory/l2/projection
  magi/memory/l2/retrieval
  magi/memory/l2/storage
  magi/memory/l3/embeddings
  magi/memory/l3/evidence
  magi/memory/l3/retrieval
  magi/memory/l3/storage
  magi/memory/l4/advisory
  magi/memory/l4/embeddings
  magi/memory/l4/learning
  magi/memory/l4/retrieval
  magi/memory/l4/storage
  magi/memory/l4/traces
  magi/runtime_trace/chat_trace/builders
  magi/chat/read
  magi/chat/storage
  magi/chat/user_turn_delivery
)

TYPE_GATE_FILES=(
  magi/llm/base.py
  magi/llm/concurrency_limiter.py
  magi/llm/streaming_events.py
  magi/llm/usage_store.py
  magi/llm/usage_tracing.py
  magi/memory/l2/batch_models.py
  magi/memory/l2/candidate_models.py
  magi/memory/l2/assertion_family_policy.py
  magi/memory/l2/entities/models.py
  magi/memory/l2/episode_models.py
  magi/memory/evidence/policy.py
  magi/memory/l2/graph_conflicts.py
  magi/memory/l2/llm_json_client.py
  magi/memory/l2/maintenance_schedule.py
  magi/memory/l2/ontology.py
  magi/memory/l2/phase1_models.py
  magi/memory/l2/phase2_models.py
  magi/memory/l2/phase_aux_models.py
  magi/memory/l2/phase_model_utils.py
  magi/memory/l2/phase_models.py
  magi/memory/l2/pipeline/context.py
  magi/memory/l2/pipeline/entities/helpers.py
  magi/memory/l2/pipeline/entities/id_resolution.py
  magi/memory/l2/pipeline/entities/side_effects.py
  magi/memory/l2/pipeline/lifecycle.py
  magi/memory/l2/pipeline/persistence.py
  magi/memory/l2/pipeline/projection.py
  magi/memory/l2/pipeline/staging.py
  magi/memory/l2/pipeline/utils.py
  magi/memory/l2/pipeline/workers.py
)

"$PYTHON_BIN" -m mypy \
  --config-file ../pyproject.toml \
  --follow-imports=skip \
  --exclude '(^|[/\\])__init__\.py$' \
  "${TYPE_GATE_DIRS[@]}" \
  "${TYPE_GATE_FILES[@]}"
