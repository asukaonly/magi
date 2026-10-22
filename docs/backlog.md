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
