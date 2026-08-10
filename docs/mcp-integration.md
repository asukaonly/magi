# MCP Client Integration

Magi can connect to external [Model Context Protocol](https://modelcontextprotocol.io) servers as a client. Their tools are wrapped as Magi `Tool`s and registered into the runtime tool registry; their resources are exposed for chat attachment via the `@`-picker (when wired). Permission gating reuses the existing brokered prompter / risk classifier — no MCP-specific gateway logic.

This document is the maintainer-facing reference.

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

`[tools].include` controls which discovered tools are registered and exposed to
the model:

```toml
[tools]
include = ["find_issues", "get_issue", "create_issue"]
```

When the section is absent, all discovered tools are exposed for compatibility.
Once an explicit list is saved, including an empty list, newly advertised tools
stay unavailable until the user selects them. The settings editor shows a
checklist after the server has connected and completed `tools/list` discovery.

`[tool_overrides.<remote-tool-name>]` lets you assign the host-owned risk level:

```toml
[tool_overrides.create_issue]
risk = "high"
```

Accepted levels are `low`, `medium`, `high`, and `destructive`. The older
`dangerous = true|false` form remains accepted and maps to `high|low`; when both
fields are present, `risk` wins.

## Tool naming and permission gating

Remote tools are exposed as `mcp__<server-id>__<remote-name>` in the registry, in a synthetic `mcp` category. MCP annotations are descriptive hints rather than authorization. The adapter translates them into the existing four-level permission vocabulary:

- `readOnlyHint: true` → `low`
- `readOnlyHint: false` and `destructiveHint: false` → `medium` (additive mutation)
- `destructiveHint: true` → `destructive`
- absent, ambiguous, or contradictory annotations → `high`

Local `tool_overrides.<name>.risk` values are authoritative. Remote hints are
not: deterministic host rules may still promote a remotely declared risk, for
example when an MCP tool name identifies an external-send operation. The
existing risk classifier and permission gateway consume the translated level;
there is no MCP-specific approval code path.

## Surfacing in the `/`-picker

The chat composer's `/`-picker only lists *user-invocable* tools — i.e. tools the user can run directly without going through the LLM. MCP tools are user-invocable when **either** rule fires:

1. The remote server marked the tool `annotations.readOnlyHint: true` in its `tools/list` response. The adapter then writes `metadata.user_invocable = true` on the wrapped `ToolSchema` automatically.
2. The fully-qualified tool name (`mcp__<server>__<remote>`) appears in the user-invocable whitelist file at `~/.magi/config/user_invocable_tools.toml`.

The whitelist is the only way to expose a tool that the server didn't annotate (or that you marked as destructive but still want to run from `/`). It is **not surfaced in the settings UI** — edit the file directly:

```toml
# ~/.magi/config/user_invocable_tools.toml
allow = [
  "mcp__github__create_issue",
  "mcp__everything__longRunningOperation",
]
```

The file is hot-reloaded on `mtime` change; no restart needed. A missing or unreadable file is treated as an empty whitelist (not an error). Built-in tools that are user-invocable by design (e.g. `web-search`) ship that flag in code and don't need an entry here.

When a tool runs via `/`, permission gating still applies normally — `dangerous` flag and `tool_overrides` behave identically to LLM-initiated calls.

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

**Tool runs without prompting that should require approval.** Check the tool's `annotations.readOnlyHint`/`destructiveHint`; force the host policy with `tool_overrides.<name>.risk`.

**MCP tool not in the `/`-picker.** Either the server didn't mark it `readOnlyHint`, or you haven't added it to the whitelist. See *Surfacing in the `/`-picker* above.

**Config not loading.** Filename stem must match `server.id`. The loader skips `index.toml`. Errors are logged with the file path.

## Smoke test

`backend/tests/mcp/test_e2e_everything.py` runs the full stack against `npx @modelcontextprotocol/server-everything`. It is auto-skipped when `npx` is unavailable. Useful when wire-format or handshake regressions are suspected.
