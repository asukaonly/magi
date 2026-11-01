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
`contracts/api/client-surface.json` classifies reachable HTTP operations into
product, optional management and device surfaces. This is an implementation
catalog, not a replacement for gateway authorization. Some existing management
responses remain dynamic; their presence in OpenAPI does not make them core
client obligations.

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

## Product events and optional diagnostics

Service protocol version 3 exposes event contract version 1. `/api/server/info`
advertises `client_contract` with the schema and stream addresses. The default
`GET /api/events?scope=product` uses `ProductEvent`, exported in
`contracts/api/frontend-product-events.json` and included in the combined OpenAPI.
Each envelope contains `contract_version`, `server_id`, `epoch`, `sequence`,
`event_id`, `event_type` and the event-specific `data` directly. Clients do not
decode a runtime notification wrapper or remap internal channel names.

The gateway projects a closed set of product events: persisted message changes,
turn/presentation status, display text previews, context usage, interaction
pointers, notification counts and resource invalidations. Unknown runtime
channels never enter this stream. Tool arguments, reasoning deltas and trace
updates stay in the authenticated, optional `scope=diagnostics` stream. Desktop
subscribes to diagnostics while its trace drawer is open; the normal chat uses
only product events. Background/delegation updates invalidate their product
snapshots instead of exposing their execution transport as the core protocol.

Each stream has independent epochs, sequence numbers, bounded retention and
subscriber capacity. Keep cursors per server **and scope**. Reset/clear invalidates
both streams. Gaps, expired cursors or malformed product data require re-reading
authoritative snapshots. The stream is a wake-up/display mechanism, never a
durable acceptance receipt. A POST confirmation read does not emit a mutation hint.

`frontend/src/client/http.ts` owns host-independent authenticated HTTP dispatch:
origin confinement, connection cancellation and read-only replay after session
renewal. The credential owner is injected. `SseClient` takes the service identity,
URL and authenticated fetch function; it imports no Tauri runtime. Desktop
composition supplies its existing credential storage and connection lifecycle.
Other platforms can implement these contracts in their own language and share
the JSON schemas and protocol scenarios without importing React or desktop launch
details. Plugins still execute on the service; clients render declared product
metadata and controls rather than loading Python plugin packages.
