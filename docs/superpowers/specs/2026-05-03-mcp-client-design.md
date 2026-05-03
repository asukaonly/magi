# MCP Client Integration — Design

Date: 2026-05-03
Status: Draft (awaiting approval)
Scope: Magi as MCP **Client**. Connect to external MCP servers and expose their **tools** and **resources** to the Magi runtime.

## 1. Goals and Non-Goals

### Goals

- Connect to MCP servers over **stdio** and **Streamable HTTP**.
- Surface remote `tools/*` as native Magi `Tool` objects in `ToolRegistry`, available to every agent path that already consumes tools (chat, planner, context-decider, recommender).
- Surface remote `resources/*` as **`@`-mention attachments** the user can mount into a chat turn (read-only, ephemeral context).
- Manage MCP connections as a **first-class config entity** under `~/.magi/config/mcp/`, independent from the existing plugin packages.
- Reuse the existing **permission gateway** (`agent/control/permission/`) for tool approvals — no parallel approval UI.

### Non-Goals (this iteration)

- MCP `prompts/*` — Magi already covers similar ground via personality/skills.
- MCP server mode (Magi exposing its own MCP endpoint).
- Sampling, elicitation, roots, completions.
- Persisting MCP resources into timeline/memory (resources stay ephemeral).
- WebSocket / legacy SSE transports (superseded by Streamable HTTP).

## 2. User-Facing Model

Two new surfaces in the frontend:

1. **Settings → MCP Servers** — list, add, edit, enable/disable, see live status (connected, connecting, error, count of tools/resources), restart, view logs.
2. **Chat composer `@` picker** — when the user types `@`, the existing mention picker gains a new section "MCP Resources", grouped by server. Selecting one mounts that resource as a read-only attachment for the next turn (and optionally pinned for the conversation).

In conversation, MCP tools appear under names like `mcp__github__create_issue`. The user does not configure them individually — enabling a server enables its tools, governed by the permission gateway.

## 3. Architecture Overview

```
┌─────────────── Frontend ───────────────┐
│ Settings: MCP Servers   Chat: @picker  │
└──────────────┬─────────────────────────┘
               │ IPC (existing channel)
┌──────────────▼─────────────────────────┐
│ Backend                                │
│                                        │
│  ┌──────────────────────────────────┐  │
│  │ MCPManager                       │  │  new
│  │  - load mcp config files         │  │
│  │  - lazy-spawn connections        │  │
│  │  - reconcile with ToolRegistry   │  │
│  │  - resource catalog              │  │
│  └────────┬──────────────┬──────────┘  │
│           │              │             │
│  ┌────────▼──┐  ┌────────▼─────────┐   │
│  │ MCPConn   │  │ MCPResourceCat.  │   │  new
│  │ (stdio/   │  │ (per-server URI  │   │
│  │  HTTP)    │  │  index, cached)  │   │
│  └────────┬──┘  └──────────────────┘   │
│           │                            │
│  ┌────────▼──────────────┐             │
│  │ ToolRegistry          │  existing   │
│  │  ← MCPToolAdapter     │  new adapter│
│  │    (subclass of Tool) │             │
│  └────────┬──────────────┘             │
│           │                            │
│  ┌────────▼──────────────┐             │
│  │ Permission Gateway    │  existing   │
│  │ (classifier + rules + │             │
│  │  brokered prompter)   │             │
│  └───────────────────────┘             │
└────────────────────────────────────────┘
```

New code lives under `backend/src/magi/mcp/`. Nothing existing moves; integration is via two seams:

- **`ToolRegistry.register(...)`** for tools.
- **A new resource catalog query API** consumed by the `@` picker (and a thin context attacher in the chat pipeline).

## 4. Components

### 4.1 `backend/src/magi/mcp/`

```
mcp/
  __init__.py
  manager.py           # MCPManager — lifecycle, reconciliation
  connection.py        # MCPConnection — base + stdio + http subclasses
  protocol.py          # JSON-RPC framing, MCP message dataclasses
  tool_adapter.py      # MCPToolAdapter(Tool) — wraps remote tool as Magi Tool
  resource_catalog.py  # In-memory index of resources per server, with cache + subscriptions
  config.py            # Pydantic models for ~/.magi/config/mcp/*.toml
  loader.py            # Read/write split TOML files, validation
  errors.py
  logs.py              # Per-server rolling log buffer for the UI
```

### 4.2 `MCPConnection`

- Abstract base with `start()`, `stop()`, `request(method, params)`, `notify(method, params)`, `on_notification(handler)`.
- `StdioConnection`: spawns subprocess, frames JSON-RPC over stdio (LSP-style `Content-Length` headers per MCP spec).
- `HttpConnection`: Streamable HTTP — POST for requests, SSE stream for server-initiated notifications.
- Reconnect policy: exponential backoff `1s, 2s, 4s, 8s, 30s` cap, max 5 attempts before flipping to `error` state. Manual restart from UI resets the counter.
- Health: heartbeat by issuing `ping` (MCP protocol) every 30s when idle.

### 4.3 `MCPManager`

- Loads config from `~/.magi/config/mcp/<server-id>.toml`.
- Lazy-starts a connection on first need: when (a) the user explicitly requests start, (b) a tool with that prefix is invoked, (c) the `@` picker requests resources for that server. Servers marked `autostart=true` start at boot.
- After `initialize` handshake, calls `tools/list` and `resources/list`, then:
  - For each tool: builds an `MCPToolAdapter` and `ToolRegistry.register(adapter_class)`.
  - For each resource: stores `(uri, name, description, mimeType)` in `resource_catalog`.
- Subscribes to `notifications/tools/list_changed` and `notifications/resources/list_changed` to re-reconcile.
- On disconnect: unregisters that server's tools from `ToolRegistry`, marks resources stale.

### 4.4 `MCPToolAdapter`

- Subclass of `magi_plugin_sdk.tools.Tool`.
- `get_schema()` returns a `ToolSchema` with:
  - `name = f"mcp__{server_id}__{remote_name}"`
  - `description = remote.description`
  - `parameters` translated from MCP JSON Schema → `ToolParameter` list.
  - `dangerous` derived from MCP `annotations.destructiveHint` (true) or `annotations.readOnlyHint` (false). If neither annotation is present, **default to `dangerous=true`** (conservative) — see §6.
- `execute(params, context)`:
  - Resolves the connection from `MCPManager`.
  - Issues `tools/call` with timeout from config (default 60s).
  - Maps MCP result to `ToolResult`. MCP error → `ToolResult(success=False, error_code=ToolErrorCode.EXECUTION_ERROR, error=...)`.
  - Surfaces `progress` notifications via the existing tool-progress channel if available; otherwise drops.

### 4.5 Resource catalog and `@` picker

- New IPC method (under existing transport): `mcp.list_resources()` returns flattened `[{server_id, uri, name, description, mimeType}]`.
- `@` picker fetches once per session and refreshes on `resources/list_changed`.
- When the user mounts a resource, the chat layer calls `mcp.read_resource(server_id, uri)`, which proxies to the connection's `resources/read`. Returned content is attached to the next turn as a system-style attachment block (existing attachment plumbing in the chat coordinator).
- Read results are cached for 60s per `(server_id, uri)` to handle the common "user previews then sends" pattern.
- **No** writes to timeline or memory.

## 5. Configuration Schema

Path: `~/.magi/config/mcp/<server-id>.toml` — one file per server, mirroring how plugins are split.

```toml
[server]
id = "github"                  # required, must match filename stem; used in tool prefix
name = "GitHub"
description = "Official GitHub MCP server"
enabled = true
autostart = false              # if false, lazy-start on first tool/resource use

[transport]
kind = "stdio"                 # "stdio" | "http"

# stdio fields (when kind="stdio")
command = "npx"
args = ["-y", "@modelcontextprotocol/server-github"]
cwd = ""                       # optional, defaults to ~/.magi
[transport.env]
GITHUB_TOKEN = "${env:GITHUB_TOKEN}"   # ${env:VAR} expansion supported

# http fields (when kind="http")
# url = "https://example.com/mcp"
# [transport.headers]
# Authorization = "Bearer ${env:MY_TOKEN}"

[runtime]
call_timeout_ms = 60000
init_timeout_ms = 15000
max_restart_attempts = 5
```

### Top-level index

`~/.magi/config/mcp/index.toml` (managed by Magi, mirrors the plugin pattern) lists known server IDs and their file paths. Hand-editing is supported but the loader rebuilds the index from disk on boot.

### Migration / discovery

A one-shot import button in Settings reads `~/.cursor/mcp.json` and `~/Library/Application Support/Claude/claude_desktop_config.json` if present, prefilling server entries.

## 6. Permission Model

Reuses `agent/control/permission/` — no new approval UI.

Mapping rules at adapter construction:

| MCP annotation                      | `ToolSchema.dangerous` | Classifier `risk_hint` |
|-------------------------------------|------------------------|------------------------|
| `readOnlyHint = true`               | false                  | LOW                    |
| `destructiveHint = true`            | true                   | HIGH                   |
| `destructiveHint = false` (and not read-only) | false        | MEDIUM                 |
| neither annotation present          | true                   | HIGH (conservative)    |

Behavior follows from the existing gateway:

- **`PermissionMode.DEFAULT`**: low-risk tools execute silently; medium/high prompt the user via the existing `brokered_prompter`. This is the user's stated requirement — default mode does not over-prompt.
- **Stricter modes**: classifier elevates levels per existing rule table; user-facing behavior matches Magi's current internal tools.
- **Plan mode**: existing `plan_mode_guard` already restricts to read-only tools — applies to MCP tools automatically because `dangerous=false` propagates.
- **Kill list**: still applies. We add a small set of MCP-specific patterns (e.g. block `tools/call` to a server while it is in `error` state) but no kill rules on remote tool *content*.

The user can override the inferred risk per `(server_id, tool_name)` in the server's TOML:

```toml
[tool_overrides."create_issue"]
dangerous = true
risk = "high"
```

## 7. Lifecycle and Failure Modes

- **Boot**: `MCPManager.start()` reads config, registers nothing yet for non-autostart servers (placeholder entries are NOT added to `ToolRegistry` — they only show up after a successful handshake, otherwise the LLM would see broken tools).
- **First use**: lazy-start triggers. While connecting, the in-flight tool call awaits up to `init_timeout_ms`; on timeout returns `ToolResult(success=False, error="MCP server <id> failed to start")`.
- **Crash mid-session**: connection emits a `disconnected` event; manager unregisters that server's tools and resources, then attempts reconnect with backoff. New tool calls during this window fail fast.
- **Schema drift after reconnect**: on every reconnect we re-fetch `tools/list` and diff. New tools registered, removed tools unregistered, changed schemas re-registered.
- **Slow tool**: `tools/call` is run with `call_timeout_ms`; on timeout we send MCP `$/cancelRequest` and return an error.

## 8. Observability

- Per-server log buffer (last 500 lines of stderr for stdio + last 100 RPC summaries) viewable in Settings.
- Standard Magi logger entries under `magi.mcp.<server_id>`.
- Metrics counters (request count, error count, p50/p95 latency) exposed alongside existing tool stats.

## 9. Testing Strategy

- **Unit**: schema translation, prefix collision handling, annotation→risk mapping, TOML loader/round-trip, env expansion.
- **Connection**: a fake `StdioConnection` fed scripted JSON-RPC turns (initialize, list, call, errors, disconnect, reconnect).
- **Integration**: spin up a real reference MCP server (the `@modelcontextprotocol/server-everything` test server) in CI and exercise tool call + resource read end-to-end.
- **Permission**: fake gateway test confirming MCP tool with `destructiveHint` is treated identically to a built-in `dangerous=True` tool.
- **Property**: invalid configs (missing command, bad JSON Schema in tool list) produce error states, never crash the manager.

## 10. Phased Delivery

A single spec, but implementation lands in three reviewable slices:

1. **Slice A — Tools over stdio**: `MCPManager`, `StdioConnection`, `MCPToolAdapter`, config loader, settings UI (list/add/enable). No resources, no HTTP. Smallest end-to-end useful product.
2. **Slice B — Resources + `@` picker**: resource catalog, IPC, frontend picker integration, attachment plumbing.
3. **Slice C — Streamable HTTP transport**: `HttpConnection`, header/env expansion for tokens, settings UI form variant.

Each slice is independently shippable and reviewable.

## 11. Risks and Open Questions

- **Tool name length**: `mcp__<server>__<tool>` increases prompt token cost. Acceptable tradeoff for unambiguity; revisit if measured impact is significant.
- **stdio process explosion**: many enabled servers each fork a subprocess. Lazy-start mitigates; we should also document recommended limits.
- **HTTP auth refresh**: `${env:VAR}` covers static tokens; OAuth refresh flows are out of scope this iteration. Users with OAuth servers will need an external token-broker until a future slice.
- **Schema mismatch**: MCP tool JSON Schema features (e.g. `oneOf`, `$ref`) that don't map cleanly to `ToolParameter`. We will reject unsupported schemas with a clear error and surface it in the server's status row.
