# Gateway Migration Plan

## Purpose

This document describes the plan to migrate the management plane (L13 External Services + L14 Transport) from the Python process into the Rust Tauri host, replacing the current HTTP proxy architecture with a direct IPC channel.

Read together with [Layered Agent Architecture](./layered-agent-architecture.md) and [Task-Agent Runtime Architecture](./task-agent-runtime-architecture.md).

## Motivation

1. The Python backend currently runs a full FastAPI/uvicorn HTTP stack (~9,500 lines) that duplicates transport concerns already handled by the Rust Axum gateway.
2. The separate API process consumes significant memory. Moving the management plane to Rust eliminates the HTTP/ASGI overhead.
3. The management plane (data display, config changes, session management) must not be blocked by the runtime plane (LLM calls, agent execution, memory processing).
4. The architecture should support multiple upper-layer hosts — desktop (Tauri), headless CLI, third-party integrations — without coupling to the Python transport layer.

## Target Architecture

```
┌─ magi-gateway (Rust lib crate) ──────────────────────────┐
│  Axum HTTP + WS Server                                   │
│  IPC Client (UDS on unix / TCP loopback on Windows)      │
│  DB Reader (rusqlite, 6 SQLite databases)                │
│  Config I/O (serde_yaml / serde_json)                    │
│  Event Relay (IPC events → Tauri Event / WS push)        │
└──────────────────────────────────────────────────────────┘
      ▲ embed                   ▲ embed
┌─────┴──────────┐    ┌────────┴──────────┐
│ Tauri Desktop  │    │ magi-gateway-cli  │
│ (GUI app)      │    │ (headless / bench)│
└────────────────┘    └───────────────────┘
      │ IPC (NDJSON over UDS / TCP loopback)
      ▼
┌─ Python Worker ──────────────────────────────────────────┐
│  IPC Server + Command Dispatcher                         │
│  L1-L12 runtime plane (unchanged)                        │
│  No HTTP / No WebSocket / No uvicorn                     │
└──────────────────────────────────────────────────────────┘
```

## Layer Ownership After Migration

| Layer | Before | After |
|-------|--------|-------|
| L14 Transport | Python (uvicorn, WebSocket) | **Rust** (Axum HTTP, WS, Tauri Event) |
| L13 Services | Python (FastAPI routers) | **Rust** (Axum handlers) |
| L2 Config write | Python (save_config) | **Rust** (serde_yaml file I/O) |
| L2 Config reload | Python (ConfigLoader singleton) | Python (unchanged, triggered by IPC notify) |
| L3 Events enqueue | Python (API handler → queue.put) | **Rust** → IPC → Python dispatcher → queue.put |
| L5-L12 Runtime | Python | Python (unchanged) |

## IPC Protocol

Transport: UDS (`asyncio.start_unix_server` / `tokio::net::UnixStream`) on macOS/Linux. TCP loopback (`127.0.0.1:port`) on Windows where Python asyncio lacks UDS support.

Framing: Newline-delimited JSON (NDJSON). Each message is a single JSON object terminated by `\n`.

### Message Types

**Rust → Python:**

```jsonc
// request (expects response or stream + response)
{"id": "uuid", "method": "send_message", "params": {...}}

// notify (fire-and-forget, no response expected)
{"method": "config_reload", "params": {"reason": "user_update"}}
```

**Python → Rust:**

```jsonc
// response (terminates a request)
{"id": "uuid", "result": {...}}

// error (terminates a request)
{"id": "uuid", "error": {"code": -1, "message": "..."}}

// stream (intermediate data for a request, 0..N before result/error)
{"id": "uuid", "stream": {"type": "token", "text": "Hello"}}

// event (unsolicited push from runtime)
{"event": "agent.status_changed", "data": {...}}
```

Rules:
- Receiving `result` or `error` for an `id` terminates that request.
- Multiple requests can be in-flight concurrently on one connection (multiplexed by `id`).
- `notify` messages have no `id` and expect no response.
- `event` messages have no `id` and are pushed by Python at any time.

## Migration Phases

### Phase 6: Remaining Read-Only Endpoint Migration

Migrate all remaining GET endpoints to Rust native handlers that read SQLite/YAML/JSON directly. Python HTTP stays as fallback but receives no read traffic.

Endpoints to migrate:

- Config: `GET /api/config/`, `GET /api/config/template`
- LLM: `GET /api/llm/providers/catalog`
- Memory: `GET /api/memory/l0/sessions`, `GET /api/memory/l1/events`, `GET /api/memory/l2/statistics`, `GET /api/memory/l2/entities`, `GET /api/memory/l2/relations`, `GET /api/memory/l3/summaries`, `GET /api/memory/search`, `GET /api/memory/background/pending`
- Personality: `GET /api/personality-config/current`, `GET /api/personality-config/list`, `GET /api/personality-config/{name}`, `GET /api/personality-presets`
- Plugins: `GET /api/plugins`
- Sensors: `GET /api/sensors/status`
- Tools/Skills: `GET /api/tools`, `GET /api/tools/{name}/config`, `GET /api/skills`
- Timeline: `GET /api/timeline/viewport`, `GET /api/timeline/context/{id}`
- Runtime: `GET /api/metrics/runtime/overview`
- Embedding: `GET /api/local-embedding/models`

Estimated Rust addition: ~1,500 lines.

### Phase 7: IPC Channel Implementation

Build the Rust IPC client and Python IPC server with cross-platform transport.

**Rust side** (`src-tauri/src/ipc/`):
- `client.rs` — IpcClient with connect, notify, request, request\_stream
- `protocol.rs` — Message types and serde
- `transport.rs` — `cfg(unix)` UDS / `cfg(windows)` TCP connect
- `event_relay.rs` — IPC events → Tauri Event emission

**Python side** (`backend/src/magi/ipc/`):
- `server.py` — IpcServer with unix/tcp listener
- `protocol.py` — Message parsing
- `dispatcher.py` — method → handler routing
- `handlers.py` — Command handler implementations

End-to-end validation: `send_message` command round-trip with stream responses.

Phase 6 and Phase 7 can proceed in parallel.

### Phase 8: Mutation Endpoint Migration

Migrate all POST/PUT/DELETE endpoints from HTTP proxy to Rust handlers that either write directly (file/DB) or dispatch IPC commands to Python.

Batches (each independently verifiable):

- **8a** Messages & sessions: send, cancel, session CRUD
- **8b** Config & LLM: config update, onboarding, LLM test/discover
- **8c** Personality & plugins: personality CRUD, plugin enable/disable/reload
- **8d** Sensors, schedules, tasks, memory writes
- **8e** Benchmark/eval endpoints

Pattern per endpoint:
- Pure file/DB write → Rust handles entirely, may send IPC notify for runtime reload
- Requires Python runtime objects → Rust sends IPC request, awaits response
- Streaming response needed → Rust sends IPC request, receives stream messages, relays to client

### Phase 9: Remove Python HTTP Stack

Delete Python transport layer (~9,500 lines):
- `api/routers/` (16 files, ~5,763 lines)
- `api/services/` (6 files, ~2,100 lines)
- `api/routes.py`, `api/responses.py`, and helpers (~400 lines)
- `websocket/` (8 files, ~1,184 lines)
- `backend_app.py` FastAPI factory (~138 lines)

Replace with `worker_app.py`: IPC server + bootstrap + runtime init.

Simplify `ProcessRole` to single `WORKER` role.

Rust side: add WebSocket handler on Axum (same port as HTTP), remove `proxy.rs` and `notification_bridge.rs`.

### Phase 10: Extract magi-gateway Lib Crate

Restructure into Cargo workspace:

```
crates/
  magi-gateway/        # Rust lib: Axum routes, IPC client, DB reader, config I/O
frontend/src-tauri/    # Tauri desktop binary, depends on magi-gateway
gateway-cli/           # Standalone headless binary, depends on magi-gateway
```

`magi-gateway-cli` enables headless operation and benchmark workflows without Tauri.

## Estimated Impact

| Phase | Rust | Python | Risk |
|-------|------|--------|------|
| 6 | +1,500 lines | no change | low |
| 7 | +400 lines | +350 lines | medium |
| 8 | +800 lines | +200 lines (handlers) | medium |
| 9 | +150 lines (WS), -100 lines (proxy/bridge) | -9,500 lines | high |
| 10 | +200 lines (CLI), refactor | no change | low |
| **Total** | **+2,950 lines** | **-8,950 lines** | |

## New Rust Dependencies

```toml
uuid = { version = "1", features = ["v4"] }
dashmap = "6"
serde_yaml = "0.9"
tokio-stream = "0.1"
```

## Status

- [x] Phase 1-5: Axum gateway, notification bridge, unified process, initial read endpoints (14 endpoints)
- [ ] Phase 6: Remaining read-only endpoints
- [ ] Phase 7: IPC channel
- [ ] Phase 8: Mutation endpoints
- [ ] Phase 9: Remove Python HTTP
- [ ] Phase 10: Extract gateway crate
