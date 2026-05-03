# MCP Client Integration

Magi can connect to external [Model Context Protocol](https://modelcontextprotocol.io) servers as a client. Their tools are wrapped as Magi `Tool`s and registered into the runtime tool registry; their resources are exposed for chat attachment via the `@`-picker (when wired). Permission gating reuses the existing brokered prompter / risk classifier — no MCP-specific gateway logic.

This document is the maintainer-facing reference. For background, see the design spec at `docs/superpowers/specs/2026-05-03-mcp-client-design.md`.

## What lives where

- **Backend module** — `backend/src/magi/mcp/`
  - `protocol.py` — JSON-RPC types + newline-delimited frame decoder
  - `connection.py` — `MCPConnection` base, `StdioConnection`, `HttpConnection` (Streamable HTTP, MCP 2025-03-26)
  - `config.py` — pydantic models (`MCPServerConfig`, transports, runtime, `ToolOverride`)
  - `loader.py` — TOML loader for `~/.magi/config/mcp/<id>.toml` with `${env:VAR}` expansion
  - `_toml_writer.py` — minimal serializer for round-tripping configs
  - `tool_adapter.py` — `build_adapter_class` wraps a remote tool into a `Tool` subclass named `mcp__<server>__<tool>`
  - `manager.py` — `MCPManager`: lifecycle, handshake (`initialize` → `initialized`), `tools/list` / `resources/list` reconciliation, change notifications, exponential-backoff reconnect watchdog
  - `lifecycle.py` — `MCPModule` registered after `runtime_tools` in the worker bootstrap
- **REST API** — `backend/src/magi/api/routers/mcp.py` — mounted at `/api/mcp` (server CRUD, start/stop, logs, resources)
- **Frontend** — `frontend/src/components/settings/MCPServersSection.tsx` (settings tab), `frontend/src/api/modules/mcp.ts` (typed client). Tab id: `mcpServers`. i18n keys under `settings.mcp.*`.

## Adding a server

There are two paths: the settings UI and editing TOML directly.

### Settings UI (recommended)

Settings → MCP Servers → **Add server**. Choose `stdio` (the default; runs a subprocess) or `http` (Streamable HTTP). For stdio, fill in `command` plus space-separated `args` and optional `KEY=VALUE` env lines. Toggle **Start on launch** if the server should boot automatically. Save persists `~/.magi/config/mcp/<id>.toml` and starts the server immediately if `enabled` and `autostart` are on.

### TOML directly

Drop a file at `~/.magi/config/mcp/<server-id>.toml`. The filename stem must equal `server.id`. Minimum stdio example:

```toml
[server]
id = "everything"
name = "Everything"
autostart = true

[transport]
kind = "stdio"
command = "npx"
args = ["-y", "@modelcontextprotocol/server-everything"]
```

HTTP transport:

```toml
[server]
id = "remote"
name = "Remote MCP"

[transport]
kind = "http"
url = "https://example.com/mcp"

[transport.headers]
Authorization = "Bearer ${env:REMOTE_TOKEN}"
```

`${env:VAR}` expansion happens at load time and is applied to every string anywhere in the document. Missing env vars expand to the empty string.

The `[runtime]` section accepts `call_timeout_ms`, `init_timeout_ms`, and `max_restart_attempts`; defaults are 60s/15s/5.

`[tool_overrides.<remote-tool-name>]` lets you force `dangerous` on or off:

```toml
[tool_overrides.create_issue]
dangerous = true
```

## Tool naming and permission gating

Remote tools are exposed as `mcp__<server-id>__<remote-name>` in the registry, in a synthetic `mcp` category. Their `dangerous` flag is inferred from MCP `annotations`:

- `readOnlyHint: true` → safe (no prompt at default mode)
- `destructiveHint: true` → dangerous (prompted)
- absent or ambiguous → **dangerous** (conservative default — flip via `tool_overrides`)

The existing risk classifier picks up the flag from `Tool.get_info()["dangerous"]`, which the function-calling permission gate already reads. There is no MCP-specific permission code path.

## Transports

### stdio

Per the MCP spec, every message is a single line of UTF-8 JSON terminated by `\n`. `connection.py` enforces "no embedded newlines" on the encode side and skips blank lines on the decode side. `stderr` is captured in a 500-line ring buffer surfaced via `GET /api/mcp/servers/{id}/logs`.

### Streamable HTTP

A single `POST <url>` carries each request with `Accept: application/json, text/event-stream`. The server may answer with either inline JSON or an SSE stream — both are supported. `Mcp-Session-Id` returned during `initialize` is propagated on every subsequent request. A best-effort `GET <url>` SSE listener is opened for server-initiated messages; HTTP 405 is treated as "no listen channel" and the client keeps working in request/response mode.

## Reconnect behavior

Each running server has a watchdog task. When `conn.state` becomes `DISCONNECTED`, all tools registered for that server are unregistered, then the manager retries `start_server` with backoff `[1, 2, 4, 8, 30]` seconds, capped at `runtime.max_restart_attempts`. After exhaustion the runtime is dropped and an error is logged. A manual `POST /api/mcp/servers/{id}/start` resets the cycle.

## Troubleshooting

**Tools not appearing in chat.** Check `Settings → MCP Servers` for the server state. Errors surface there as a red caption; full `stderr` is at `GET /api/mcp/servers/{id}/logs`.

**Server won't connect.** stdio: confirm the `command` is on PATH and the package can run; e.g. `npx -y @modelcontextprotocol/server-everything` from a terminal. HTTP: confirm `Accept: application/json, text/event-stream` is supported by the server.

**Tool runs without prompting that should require approval.** Check the tool's `annotations.readOnlyHint`/`destructiveHint`; force with `tool_overrides.<name>.dangerous`.

**Config not loading.** Filename stem must match `server.id`. The loader skips `index.toml`. Errors are logged with the file path.

## Smoke test

`backend/tests/mcp/test_e2e_everything.py` runs the full stack against `npx @modelcontextprotocol/server-everything`. It is auto-skipped when `npx` is unavailable. Useful when wire-format or handshake regressions are suspected.
