# Client–Server Contract

Magi clients present product state and collect explicitly authorized device data.
The service owns conversation acceptance, execution, persistence, plugin execution,
memory, scheduling and conflict arbitration. iOS, Android and desktop use the same
HTTP product boundary; a desktop's local service launcher is not part of that boundary.

## Contract ownership

- Product contracts cover sessions, messages, turn status, interactions, personal
  tasks, timeline entries, attachments and notifications.
- Management contracts cover server settings, plugin installation/configuration,
  memory operations and diagnostics. A client implements only the management
  surfaces it presents. It does not reproduce worker bootstrap or plugin loading.
- Device collection is a separately authorized contribution to a source. It does
  not grant configuration, arbitrary tool execution or plugin installation rights.

The gateway's authenticated `/api/openapi.json` describes reachable native and
Python operations. `contracts/api/gateway_routes.json` owns native route access;
Python product routes must pass `_PUBLIC_ROUTE_METHODS`. Generated JSON contracts
under `contracts/api/` are language-independent. The TypeScript models and validators
are one consumer, not the protocol definition or a requirement for native clients.

## Exact send confirmation and turn state

`contracts/api/frontend-client.json` is generated from production public routes.
It includes paths, request unions and closed response schemas:

| Operation | Meaning |
| --- | --- |
| `POST /api/messages/confirmation` | Read whether the exact turn or question answer was accepted; never dispatch work |
| `GET /api/messages/session/{session_id}/turn/{turn_id}` | Read acceptance and execution/presentation status from a consistent chat-store snapshot |

A turn confirmation carries `kind: turn`, `session_id`, and the stable `turn_id`
originally supplied as `client_turn_id`. An answer confirmation carries
`kind: ask_response`, `session_id`, `request_id`, and the exact `answer`. Do not
infer either result from the last page of messages or the latest question.

Receipts return `confirmed`, `absent`, or `concluded` with `safe_to_retry`.
Retry only when authorized by a successful receipt and reuse the original identity
and payload. A timeout or unavailable store is unknown, not absence. The response
is an observation, not a reservation; concurrent requests still arbitrate through
the existing acceptance/answer transaction. An answered question remains
confirmable after a newer question opens and after restart. A different answer,
expired/cancelled question, or retired turn is not retryable. Worker restart
cancels questions whose continuations no longer exist; it does not revive permissions.

Turn snapshots read the persisted user-message anchor and `chat_turns` together.
An accepted anchor can precede runtime scheduling (`queued`). Deleted/archived
sessions and retired identities are `retired`; they cannot be recreated by retry.
`terminal` describes execution. `response_complete` describes complete persisted
response segments. `presentation_ends_at_ms` describes when all persisted bubbles
may be displayed. A terminal execution can still have future presentation work.
`revision` is an opaque chat-read revision, not a runtime sequence number.

Desktop uses these endpoints for uncertain-send confirmation and pending-turn
reconciliation. History remains the content snapshot. Local rendering can delay
bubbles, but cannot decide whether a command was durably accepted. Personal tasks
remain a separate domain from chat turns and execution traces.
