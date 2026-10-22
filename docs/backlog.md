# Magi Backlog

This document tracks concrete, code-backed engineering work that remains open.
Every item must describe a current failure mode or boundary violation and have
an independently verifiable completion condition.

Product choices, speculative abstractions, permanent engineering principles,
and completed migration history do not belong here. Local decision drafts and
implementation spikes belong under `docs/dev/`; durable decisions must be
folded into the relevant source-of-truth document before implementation.

## Active Engineering

### 1. Add durable per-target external conversation delivery

Status: active

Current failure mode:

- ordinary external replies are delivered before their receipts are persisted
- external `ask_user` delivery has only process-local deduplication and performs
  a single attempt
- a restart after provider acceptance but before local acknowledgement cannot
  safely distinguish a missing delivery from a duplicate retry

Required outcome:

- persist one delivery intent per target before invoking the channel provider
- give every final reply and ask a stable host delivery identity
- lease and retry unfinished intents after restart without reusing the
  proactive-outreach lifecycle
- extend the channel contract so capable providers can apply the stable identity
  as an idempotency key
- expire or cancel asks that are no longer actionable
- cover the provider-accepted/local-acknowledgement crash window, partial fanout,
  retry, expiry, and clear/delete behavior with focused tests

### 2. Extract application services from oversized memory routers

Status: active

Current failure mode:

- `memory/l2/experiences_routes.py` and `memory/manual_entries_routes.py` still
  own substantial business orchestration
- `memory/l2/correction_history.py` performs storage queries inside the API
  package
- memory router dependency helpers contain repeated runtime/domain resolution
  logic

Required outcome:

- move experience and manual-entry orchestration into domain/application
  services with explicit inputs and outputs
- move correction-history persistence and privacy filtering behind a
  repository/application boundary
- make HTTP handlers responsible only for request validation, dependency
  resolution, status/error translation, and response serialization
- reuse the same application paths from any non-HTTP entry point
- preserve public API contracts with focused service, router, and reachability
  tests
