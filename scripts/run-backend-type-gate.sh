#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON:-python}"

cd "$ROOT_DIR/backend"

export PYTHONPATH="$ROOT_DIR/backend/src:$ROOT_DIR/sdk/src${PYTHONPATH:+:$PYTHONPATH}"

"$PYTHON_BIN" -m mypy \
  --config-file pyproject.toml \
  --follow-imports=skip \
  src/magi/agent/execution/function_calling/failures.py \
  src/magi/agent/execution/function_calling/fallback.py \
  src/magi/agent/execution/function_calling/guardrails.py \
  src/magi/agent/execution/function_calling/llm.py \
  src/magi/agent/execution/function_calling/messages.py \
  src/magi/agent/execution/function_calling/permission.py \
  src/magi/agent/execution/function_calling/postprocessor.py \
  src/magi/agent/execution/function_calling/responses.py \
  src/magi/agent/execution/function_calling/step_executor.py \
  src/magi/agent/execution/function_calling/tool_execution.py \
  src/magi/agent/execution/function_calling/tracing.py \
  src/magi/agent/execution/function_calling/types.py \
  src/magi/agent/task_agents/chat/postprocess/background.py \
  src/magi/agent/task_agents/chat/postprocess/intent.py \
  src/magi/agent/task_agents/chat/postprocess/memory.py \
  src/magi/agent/task_agents/chat/postprocess/outcomes.py \
  src/magi/agent/task_agents/chat/postprocess/session.py \
  src/magi/agent/task_agents/chat/postprocess/tool_events.py \
  src/magi/agent/workers/worker_actions.py \
  src/magi/agent/workers/worker_launch.py \
  src/magi/agent/workers/worker_prompting.py \
  src/magi/agent/workers/worker_publication.py \
  src/magi/agent/workers/worker_schema.py \
  src/magi/agent/workers/worker_status.py \
  src/magi/llm/base.py \
  src/magi/llm/concurrency_limiter.py \
  src/magi/llm/provider_bridge/options.py \
  src/magi/llm/provider_bridge/requests.py \
  src/magi/llm/provider_bridge/streaming.py \
  src/magi/llm/streaming_events.py \
  src/magi/llm/usage_events.py \
  src/magi/llm/parsers/content_sanitizer.py \
  src/magi/llm/parsers/tool_call_parser.py \
  src/magi/memory/l1/event_store_embeddings.py \
  src/magi/memory/l1/event_store_entities.py \
  src/magi/memory/l1/event_store_fts.py \
  src/magi/memory/l1/event_store_queries.py \
  src/magi/memory/l1/event_store_rows.py \
  src/magi/memory/l1/event_store_schema.py \
  src/magi/memory/l2/batch_models.py \
  src/magi/memory/l2/candidate_models.py \
  src/magi/memory/l2/ontology.py \
  src/magi/memory/l2/pipeline/validation/assertions.py \
  src/magi/memory/l2/evidence_policy.py \
  src/magi/memory/l2/graph_conflicts.py \
  src/magi/memory/l2/llm_json_client.py \
  src/magi/memory/l2/maintenance_schedule.py \
  src/magi/memory/l2/entity_maintenance_assertions.py \
  src/magi/memory/l2/entity_maintenance_catalog.py \
  src/magi/memory/l2/entity_maintenance_edges.py \
  src/magi/memory/l2/entity_maintenance_embeddings.py \
  src/magi/memory/l2/entity_maintenance_episodes.py \
  src/magi/memory/l2/entity_maintenance_ghosts.py \
  src/magi/memory/l2/entity_maintenance_predicates.py \
  src/magi/memory/l2/entity_catalog_embeddings.py \
  src/magi/memory/l2/entity_catalog_queries.py \
  src/magi/memory/l2/entity_models.py \
  src/magi/memory/l2/episode_models.py \
  src/magi/memory/l2/phase1_models.py \
  src/magi/memory/l2/phase2_models.py \
  src/magi/memory/l2/phase_aux_models.py \
  src/magi/memory/l2/phase_model_utils.py \
  src/magi/memory/l2/phase_models.py \
  src/magi/memory/l2/pipeline/context.py \
  src/magi/memory/l2/pipeline/entities/id_resolution.py \
  src/magi/memory/l2/pipeline/entities/helpers.py \
  src/magi/memory/l2/pipeline/entities/side_effects.py \
  src/magi/memory/l2/pipeline/validation/graph.py \
  src/magi/memory/l2/pipeline/lifecycle.py \
  src/magi/memory/l2/pipeline/persistence.py \
  src/magi/memory/l2/pipeline/projection.py \
  src/magi/memory/l2/pipeline/staging.py \
  src/magi/memory/l2/pipeline/validation/structured_hints.py \
  src/magi/memory/l2/pipeline/utils.py \
  src/magi/memory/l2/pipeline/workers.py \
  src/magi/memory/l2/projection/claiming.py \
  src/magi/memory/l2/pipeline/prompts/workflows.py \
  src/magi/memory/l2/assertions/contradictions.py \
  src/magi/memory/l2/assertions/feedback.py \
  src/magi/memory/l2/assertions/reconcile.py \
  src/magi/memory/l2/assertions/snapshots.py \
  src/magi/memory/l2/assertions/write.py \
  src/magi/memory/l2/extraction/candidates.py \
  src/magi/memory/l2/governance/forgetting.py \
  src/magi/memory/l2/graph/conflicts.py \
  src/magi/memory/l2/graph/edge_embeddings.py \
  src/magi/memory/l2/graph/fact_kind.py \
  src/magi/memory/l2/graph/writes.py \
  src/magi/memory/l2/retrieval/queries.py \
  src/magi/memory/l2/storage/migrations.py \
  src/magi/memory/l2/storage/rows.py \
