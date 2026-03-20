# Chat Session Store Design

## Goal

Replace the current mixed chat-session model with a canonical session entity:

- chat sessions are stored in a dedicated SQLite table
- frontend owns the currently selected session
- backend chat APIs require explicit `session_id` for session-scoped reads and writes
- `chat_sessions.json` and all backend current-session fallback logic are removed

## Current Problems

The current implementation splits chat-session semantics across three places:

1. `fact_events` in L1 are aggregated to infer the session list
2. `chat_sessions.json` stores current-session pointers and title overrides
3. frontend also keeps a local current-session selection

That causes several architectural problems:

- session list performance degrades with message volume because the backend must aggregate L1 facts
- session metadata such as title and summary do not have a canonical storage model
- backend "current session" fallback makes transport contracts ambiguous
- runtime and API paths each keep partial session state, which creates drift risk

## Final Architecture

### Canonical session entity

Introduce a dedicated `chat_sessions` table in the L1 chat database domain. The table owns session metadata and list-page read performance. `fact_events` remain the source of chat message history, but sessions are no longer inferred from facts on every read.

Recommended table shape:

- `session_id TEXT PRIMARY KEY`
- `user_id TEXT NOT NULL`
- `title TEXT NOT NULL`
- `summary TEXT NOT NULL DEFAULT ''`
- `created_at REAL NOT NULL`
- `updated_at REAL NOT NULL`
- `last_message_at REAL`
- `last_user_message_at REAL`
- `last_message_preview TEXT NOT NULL DEFAULT ''`
- `last_user_message_preview TEXT NOT NULL DEFAULT ''`
- `message_count INTEGER NOT NULL DEFAULT 0`
- `archived_at REAL`
- `deleted_at REAL`

Recommended indexes:

- `(user_id, deleted_at, archived_at, updated_at DESC)`
- `(user_id, last_message_at DESC)`

### Ownership boundaries

- `chat_sessions` owns session metadata and session-list reads
- `fact_events` owns durable chat message facts and per-session history reads
- `runtime_trace.db` owns per-turn execution traces keyed by `session_id`
- frontend owns current-session selection in store/local persistence
- backend no longer stores `current_session_by_user`

## API Contract Changes

### Keep

- `GET /messages/sessions`
- `POST /messages/session/new`
- `PATCH /messages/session/{session_id}`
- `DELETE /messages/session/{session_id}`
- `GET /messages/history`
- `POST /messages/send`
- `GET /messages/trace`
- `POST /messages/history/clear`

### Remove

- `GET /messages/session/current`
- websocket `get_current_session`

### New request rules

The following calls must require explicit `session_id`:

- `POST /messages/send`
- `GET /messages/history`
- `GET /messages/trace`
- `POST /messages/history/clear`
- websocket `send_message`
- websocket `get_history`

If `session_id` is missing, the backend should reject the request with a clear `400`-class validation error. No implicit session creation or fallback resolution remains on the backend.

## Write Path

### Creating a session

`POST /messages/session/new` inserts a row into `chat_sessions` and returns the created record id. The frontend decides whether to select it immediately.

### Sending a message

When a user sends a message:

1. transport validates `session_id`
2. dispatch publishes `USER_MESSAGE` with that `session_id`
3. L1 writes the message fact into `fact_events`
4. session metadata is updated in `chat_sessions`
   - `updated_at`
   - `last_message_at`
   - `last_user_message_at`
   - `last_message_preview`
   - `last_user_message_preview`
   - `message_count`

When an AI response is persisted, the same session row is updated again with the assistant-side preview and timestamp.

## Read Path

### Session list

`GET /messages/sessions` reads directly from `chat_sessions`, ordered by most recently updated session. No L1 aggregation is required.

### Session history

`GET /messages/history?session_id=...` reads chat facts from `fact_events` for that specific session and enriches assistant turns with trace summaries from `runtime_trace.db`.

## Runtime Changes

`ChatTaskAgent` and chat runtime services should no longer own persistent session-pointer state.

`ChatSessionService` remains useful for:

- lazy history loading by `(user_id, session_id)`
- in-memory prompt history cache
- recent tool-interaction cache

But it should stop owning:

- current-session resolution
- session creation persistence
- file-backed session mapping

The runtime should treat `session_id` as required input from the incoming fact.

## Frontend Changes

The frontend should use this flow:

1. request session list
2. resolve selected session locally
   - prefer locally stored last-selected session if it still exists
   - otherwise use the newest session from the list
   - otherwise create a new session explicitly
3. request history for that selected session
4. send messages with explicit `session_id`

This makes the selection model deterministic and removes the need for backend current-session discovery.

## Migration Strategy

This project is in active development mode, so no compatibility path is needed.

Migration approach:

1. add `chat_sessions` table and storage service
2. switch session list and metadata operations to the new table
3. remove backend current-session fallback and file-backed session state
4. update frontend to own session selection
5. delete `chat_sessions.json` usage and current-session endpoints/messages

## Testing Strategy

Required coverage:

- session creation, listing, rename, and delete against `chat_sessions`
- session metadata updates when user/assistant chat facts are persisted
- rejection when session-scoped APIs omit `session_id`
- frontend initialization from explicit session list selection
- no regressions in history rendering and trace loading for selected sessions

## Expected Outcome

After this redesign:

- session list reads are stable and cheap
- session metadata has a canonical schema
- the frontend owns selected-session UX cleanly
- backend transport contracts become explicit and easier to reason about
- `chat_sessions.json` disappears entirely
