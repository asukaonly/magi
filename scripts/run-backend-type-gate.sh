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
  src/magi/memory/l2/pipeline_assertions.py \
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
  src/magi/memory/l2/pipeline_context.py \
  src/magi/memory/l2/pipeline_entity_id_resolution.py \
  src/magi/memory/l2/pipeline_entity_helpers.py \
  src/magi/memory/l2/pipeline_entity_side_effects.py \
  src/magi/memory/l2/pipeline_graph_validation.py \
  src/magi/memory/l2/pipeline_lifecycle.py \
  src/magi/memory/l2/pipeline_persistence.py \
  src/magi/memory/l2/pipeline_projection.py \
  src/magi/memory/l2/pipeline_staging.py \
  src/magi/memory/l2/pipeline_structured_hints.py \
  src/magi/memory/l2/pipeline_utils.py \
  src/magi/memory/l2/pipeline_workers.py \
  src/magi/memory/l2/projection_queue_claiming.py \
  src/magi/memory/l2/workflow_prompts.py \
  src/magi/memory/l2/store_parts/assertions.py \
  src/magi/memory/l2/store_parts/candidates.py \
  src/magi/memory/l2/store_parts/contradictions.py \
  src/magi/memory/l2/store_parts/edge_embeddings.py \
  src/magi/memory/l2/store_parts/fact_kind.py \
  src/magi/memory/l2/store_parts/feedback.py \
  src/magi/memory/l2/store_parts/forgetting.py \
  src/magi/memory/l2/store_parts/graph_conflicts.py \
  src/magi/memory/l2/store_parts/graph_writes.py \
  src/magi/memory/l2/store_parts/migrations.py \
  src/magi/memory/l2/store_parts/queries.py \
  src/magi/memory/l2/store_parts/reconcile.py \
  src/magi/memory/l2/store_parts/rows.py \
  src/magi/memory/l2/store_parts/snapshots.py
