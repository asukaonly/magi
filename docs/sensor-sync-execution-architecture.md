# Sensor Sync Execution Architecture

## Purpose

This document defines the target execution model for pull-based `sensor_sync` jobs.

Its primary goal is to ensure that no single sensor implementation can block the
main scheduler event loop. It also defines the durable queue semantics that prevent
same-target backlog growth when one sync run is already queued or running.

Read this together with:

- [Task-Agent Runtime Architecture](./task-agent-runtime-architecture.md)
- [Layered Agent Architecture](./layered-agent-architecture.md)
- [Memory System Design](./memory-system-design.md)

## Problem

The current runtime executes the full pull-sync chain directly inside the scheduler
handler:

1. collect source items
2. fetch item details
3. build sensor outputs
4. ingest outputs into memory and timeline stores

This makes the scheduler sensitive to blocking sensor code. Several built-in sensors
perform synchronous file or SQLite access in `collect_items()`, which means one slow
or blocking sensor can stall unrelated scheduled work.

## Goals

- keep the scheduler responsible only for timing, target mutual exclusion, and
  durable execution bookkeeping
- prevent any pull-sync sensor from blocking the scheduler event loop
- preserve one-outstanding-job semantics per `(target_type, target_key)`
- preserve restart recovery for queued or interrupted sensor sync jobs
- avoid changing the public `SensorBase` API in the first phase

## Non-Goals

- introducing a separate process boundary in phase 1
- parallelizing pull-sync execution across multiple worker threads
- redesigning sensors into factory-created per-run instances
- changing `memory_l2_maintenance` scheduling behavior
- adding new UI surfaces for queue monitoring in phase 1

## Architecture Summary

The runtime splits `sensor_sync` into two stages:

1. `SchedulerService` handles the APScheduler trigger and enqueues durable sensor
   work.
2. `SensorSyncExecutor` runs the actual pull-sync work on a dedicated thread with
   its own asyncio event loop.

The scheduler must no longer execute any sensor plugin code directly.

## Ownership

- scheduler timing, persisted schedules, target lock read models:
  `backend/src/magi/scheduler/`
- sensor sync queueing and execution:
  `backend/src/magi/awareness/`
- sensor output ingestion:
  `backend/src/magi/awareness/ingestion_gateway.py`

This keeps the scheduler as infrastructure while keeping sensor runtime execution in
the awareness layer.

## Runtime Flow

### Scheduled sync flow

1. APScheduler fires a `sensor_sync` schedule.
2. `SchedulerService.execute_schedule()` loads the persisted schedule.
3. For `sensor_sync`, the scheduler checks whether the target already has an
   outstanding queued or running sensor job.
4. If a job already exists, the trigger is coalesced and no new sensor job is
   created.
5. If no outstanding job exists, the scheduler creates:
   - one `schedule_executions` row
   - one `sensor_sync_jobs` row with status `queued`
6. The scheduler returns immediately without calling any sensor methods.
7. `SensorSyncExecutor` claims queued jobs on its dedicated thread.
8. The executor performs:
   - `collect_items()`
   - `fetch_item()`
   - `build_output()`
   - `extract_metadata()`
   - ingestion through `SensorIngestionGateway`
9. The executor writes final success or failure state back to scheduler storage.

### Manual sync flow

Manual sensor sync requests reuse the same queueing model. A manual trigger must not
create a second outstanding job for the same target. If a queued or running job
already exists for that source, the manual request resolves to the existing in-flight
work instead of creating backlog.

### Sensor state flush flow

Sensor runtime-state flushes must run on the same dedicated execution thread used for
pull-sync sensors. This avoids cross-thread access to the same sensor instances.

## Thread Model

Phase 1 uses one dedicated sensor-execution thread.

Rules:

- pull-sync sensor methods must run only on the sensor executor thread
- the scheduler thread must not call pull-sync sensor methods
- executor-owned async collaborators must be created in the executor thread
- sensor instances remain shared runtime registrations, so cross-thread invocation is
  not allowed

This model is intentionally conservative. It isolates the scheduler from blocking
sensor work without requiring per-run sensor factories.

## Durable Queue Model

The scheduler database owns a new `sensor_sync_jobs` table.

Required fields:

- `job_id`
- `schedule_id`
- `execution_id`
- `target_type`
- `target_key`
- `plugin_id`
- `source_type`
- `manual`
- `status`
- `payload_json`
- `created_at`
- `claimed_at`
- `started_at`
- `finished_at`
- `claimed_by`
- `attempt_count`
- `error`
- `result_message`
- `stats_json`
- `next_cursor`
- `watermark_ts`

Allowed statuses:

- `queued`
- `running`
- `success`
- `failed`
- `cancelled`

## Outstanding Job Constraint

For `sensor_sync`, there must be at most one outstanding job per target.

Outstanding means:

- `queued`
- `running`

The system enforces this in two places:

1. application-level enqueue checks
2. a database uniqueness guard for outstanding jobs per target

This preserves the existing skip/coalesce expectation:

- if the previous sync has not finished, the next trigger does not pile up another
  same-target job
- a slow sensor causes skipped ticks, not backlog growth

## State Semantics

### `schedule_executions`

`schedule_executions` remains the scheduler-facing execution log. For `sensor_sync`,
it records:

- the trigger that attempted enqueue
- whether that trigger produced a durable sensor job
- the final result of the queued execution after the executor finishes

### `target_state`

`target_state` remains a read model, not the sole execution truth.

For `sensor_sync`, authoritative in-flight status comes from `sensor_sync_jobs`.
`target_state` is updated from queued execution outcomes so existing read paths can
continue to expose:

- `running`
- `last_success_at`
- `last_error`
- `last_cursor`
- `watermark_ts`
- `next_run_at`

## Recovery Model

### Application restart

On startup:

- `queued` sensor jobs remain `queued`
- `running` sensor jobs are requeued
- stale claim metadata is cleared

The executor then resumes claiming from the queue.

### Executor crash

The executor is supervised by the runtime. If the thread stops unexpectedly:

- the supervisor restarts it
- the restarted executor requeues stale `running` jobs
- queued work resumes without scheduler intervention

### Timeout handling

Phase 1 supports stale-job recovery with bounded retries.

Recommended behavior:

- detect stale `running` jobs using `started_at`
- mark timed-out jobs as failed and release target state
- keep `attempt_count` so pathological sensors do not retry forever

Automatic backoff policy is out of scope for phase 1.

## Compatibility Notes

- `SensorBase` public APIs remain unchanged in phase 1
- plugin-contributed sensors do not need immediate rewrites to participate
- `memory_l2_maintenance` keeps the existing direct scheduler execution path

## Implementation Notes

Phase 1 should introduce:

- repository support for `sensor_sync_jobs`
- enqueue-only scheduler handling for `sensor_sync`
- one dedicated `SensorSyncExecutor`
- executor-thread routing for sensor runtime-state flushes
- recovery and regression tests for queue coalescing, restart recovery, and scheduler
  isolation
