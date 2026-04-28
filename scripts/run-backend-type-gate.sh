#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON:-python}"

cd "$ROOT_DIR/backend"

export PYTHONPATH="$ROOT_DIR/backend/src:$ROOT_DIR/sdk/src${PYTHONPATH:+:$PYTHONPATH}"

"$PYTHON_BIN" -m mypy \
  --config-file pyproject.toml \
  --follow-imports=skip \
  src/magi/agent/execution/function_calling_failures.py \
  src/magi/agent/execution/function_calling_guardrails.py \
  src/magi/agent/execution/function_calling_llm.py \
  src/magi/agent/execution/function_calling_messages.py \
  src/magi/agent/execution/function_calling_permission.py \
  src/magi/agent/execution/function_calling_postprocessor.py \
  src/magi/agent/execution/function_calling_responses.py \
  src/magi/agent/execution/function_calling_step_executor.py \
  src/magi/agent/execution/function_calling_tracing.py \
  src/magi/agent/execution/function_calling_types.py \
  src/magi/agent/task_agents/chat/postprocess_background.py \
  src/magi/agent/task_agents/chat/postprocess_memory.py \
  src/magi/agent/task_agents/chat/postprocess_outcomes.py \
  src/magi/agent/task_agents/chat/postprocess_session.py \
  src/magi/agent/task_agents/chat/postprocess_tool_events.py \
  src/magi/agent/workers/worker_actions.py \
  src/magi/agent/workers/worker_launch.py \
  src/magi/agent/workers/worker_prompting.py \
  src/magi/agent/workers/worker_schema.py \
  src/magi/agent/workers/worker_status.py \
  src/magi/llm/base.py \
  src/magi/llm/concurrency_limiter.py \
  src/magi/llm/provider_bridge_options.py \
  src/magi/llm/provider_bridge_requests.py \
  src/magi/llm/provider_bridge_streaming.py \
  src/magi/llm/streaming_events.py \
  src/magi/llm/usage_events.py \
  src/magi/llm/parsers/content_sanitizer.py \
  src/magi/llm/parsers/tool_call_parser.py \
  src/magi/memory/l2/ontology.py \
  src/magi/memory/l2/evidence_policy.py \
  src/magi/memory/l2/graph_conflicts.py \
  src/magi/memory/l2/maintenance_schedule.py \
  src/magi/memory/l2/store_assertions.py \
  src/magi/memory/l2/store_candidates.py \
  src/magi/memory/l2/store_contradictions.py \
  src/magi/memory/l2/store_edge_embeddings.py \
  src/magi/memory/l2/store_fact_kind.py \
  src/magi/memory/l2/store_feedback.py \
  src/magi/memory/l2/store_forgetting.py \
  src/magi/memory/l2/store_migrations.py \
  src/magi/memory/l2/store_queries.py \
  src/magi/memory/l2/store_graph_conflicts.py \
  src/magi/memory/l2/store_graph_writes.py \
  src/magi/memory/l2/store_reconcile.py \
  src/magi/memory/l2/store_rows.py \
  src/magi/memory/l2/store_snapshots.py
