# Unified Asset Resolver Architecture

**Status**: Proposed
**Owner**: Memory and Plugin runtime maintainers
**Last Updated**: 2026-04-28

## 1. Purpose

This document defines a unified architecture for resolving reusable
`asset_refs` returned by `memory_query`, plugin tools, and assistant reply
payloads.

The design replaces source-specific resolver tools in the agent-visible tool
surface with one host-owned `asset_resolve` tool. Source-specific logic remains
inside plugins through a new SDK resolver contract.

This keeps the LLM tool context short while giving follow-up questions a stable
path from memory evidence to concrete source facts such as local photo files,
git changed files, commit ranges, browser artifacts, or future plugin-owned
assets.

## 2. Problem

Magi already has the beginning of a reusable asset contract:

- `memory_query` can return `historical_recall.asset_refs`.
- Assistant final payloads can persist sanitized `asset_refs` for reply-turn
  continuity.
- The photo-library plugin already projects photo session events into
  `asset_refs` and contributes a source-specific resolver tool,
  `photo_library_resolve_photo_refs`.

However the current model does not scale cleanly:

1. Source-specific resolver tools leak into the agent-visible tool list.
   `photo_library_resolve_photo_refs` works, but each new source would add
   another tool name and more routing examples.
2. The router must learn source-specific follow-up patterns. The current
   `ContextDecider` has a photo-specific few-shot for sending previously found
   photos.
3. Git activity recall has enough L1 provenance to identify a repository and
   commit range, but there is no resolver path from a `git_session_*` asset ref
   to `git log`, `git diff --name-status`, or `git diff --stat` facts.
4. When a user asks a domain follow-up such as "what code changed?", the system
   can confuse it with a runtime trace follow-up and select `trace_query`.
5. Web search fallback can pollute local evidence questions when the desired
   answer is behind a local reusable asset.

The root issue is not missing git commands. The missing abstraction is a
source-neutral way to resolve an asset reference into source-specific evidence.

## 3. Goals

- Expose one compact agent-visible tool, `asset_resolve`, for reusable asset
  follow-ups.
- Move source-specific resolution into plugin-owned resolver hooks.
- Let `asset_refs` declare their resolver capability in a generic shape.
- Preserve host ownership of chat attachment import through
  `prepare_chat_attachments`.
- Support local evidence scopes without adding source-specific tool routing
  rules for every plugin.
- Enable `git_activity` follow-ups to produce verified code facts instead of
  inferred summaries from commit messages.
- Keep raw local paths out of long-lived chat payloads and prompt continuity.

## 4. Non-Goals

- A general-purpose git assistant or full git porcelain API.
- Replacing bash / PowerShell tools for explicit user-requested shell work.
- Persisting large diffs, patches, or raw file contents in L1 memory.
- Making plugin code depend on backend registries, stores, or scheduler
  internals.
- Exposing raw local file paths directly to users as the durable chat contract.

## 5. Existing State

### 5.1 Host Memory and Chat Contracts

Current host-owned pieces:

- `memory_query` projects retrieval results into `historical_recall`.
- `historical_recall.asset_refs` is built from L1 events and plugin recall
  artifacts.
- `ChatOutcomeWriter` persists assistant payload metadata.
- Reply-turn context summarizes prior assistant payloads and reinjects reusable
  `asset_refs`.
- `prepare_chat_attachments` imports concrete local files into managed chat
  attachment storage.

The reusable host contract is already named `asset_refs`; this design keeps
that name and strengthens its semantics.

### 5.2 Photo Library Plugin

The external photo plugin currently implements the pattern this design
generalizes:

- `PhotoLibraryPlugin.build_recall_artifacts(...)` projects photo session L1
  events into `asset_refs`.
- `photo_library_resolve_photo_refs` resolves `asset_ref_ids` back to current
  local photo paths.
- The chat flow then calls `prepare_chat_attachments` with resolved
  `file_paths`.

This works, but the resolver is exposed as a source-specific tool name. The
agent must learn that name.

### 5.3 Git Activity Plugin

The external git activity plugin currently contributes:

- a timeline sensor
- normalized L1 provenance with `repo_path`, `first_sha`, `last_sha`,
  `operation_counts`, `representative_messages`, and session timestamps
- L3 summary feature extraction

It does not yet contribute:

- `build_recall_artifacts(...)` for `git_activity` asset refs
- any resolver for expanding a git session into changed files or diff stats

## 6. Proposed Architecture

### 6.1 High-Level Flow

```text
L1 event / plugin recall artifact
        |
        v
historical_recall.asset_refs
        |
        v
assistant payload / reply context
        |
        v
asset_resolve(asset_ref_ids, operation)
        |
        v
PluginManager dispatches by source_type
        |
        v
source plugin resolver returns structured evidence
        |
        +--> answer directly from evidence
        |
        +--> optionally prepare_chat_attachments(file_paths)
```

The agent only sees `asset_resolve`. It does not need to know whether a photo,
git session, browser visit, or future asset type uses file scanning, git CLI,
database lookup, or external metadata internally.

### 6.2 Agent-Visible Tool

Add one built-in tool:

```text
asset_resolve
```

Parameters:

| Name | Type | Required | Description |
| --- | --- | --- | --- |
| `asset_ref_ids` | array[string] | false | Asset ids returned by memory or prior tool output. |
| `asset_refs` | array[object] | false | Optional full asset refs when the model has them in context. |
| `operation` | string enum | true | `inspect`, `files`, `attachments`, `diff_stat`, or `patch`. |
| `detail_level` | string enum | false | `summary`, `stat`, or `full`. Defaults to `summary`. |

Tool description should be short:

> Resolve reusable asset refs returned by memory or prior tool output into
> source-specific details. Use when the user asks to inspect, expand, send, or
> list files/changes behind referenced assets.

The tool is host-owned and registered in core tools. It dispatches to plugin
resolvers through `PluginManager`.

### 6.3 SDK Resolver Contract

Add SDK DTOs to `magi_plugin_sdk.contracts` or a small new
`magi_plugin_sdk.assets` module. Re-export them from `magi_plugin_sdk.__init__`.

```python
class AssetResolverSpec(BaseModel):
    source_type: str
    supported_kinds: list[str] = Field(default_factory=list)
    supported_operations: list[str] = Field(default_factory=list)
    output_capabilities: list[str] = Field(default_factory=list)
    max_batch_size: int = 20


class AssetResolveRequest(BaseModel):
    source_type: str
    asset_ref_ids: list[str] = Field(default_factory=list)
    asset_refs: list[dict[str, Any]] = Field(default_factory=list)
    operation: Literal["inspect", "files", "attachments", "diff_stat", "patch"] = "inspect"
    detail_level: Literal["summary", "stat", "full"] = "summary"
    context: dict[str, Any] = Field(default_factory=dict)


class AssetResolveResult(BaseModel):
    source_type: str
    resolved_asset_refs: list[dict[str, Any]] = Field(default_factory=list)
    items: list[dict[str, Any]] = Field(default_factory=list)
    file_paths: list[str] = Field(default_factory=list)
    changed_files: list[dict[str, Any]] = Field(default_factory=list)
    commits: list[dict[str, Any]] = Field(default_factory=list)
    diff_stat: str | None = None
    summary: str = ""
    missing_asset_ref_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
```

Extend the plugin base class:

```python
class Plugin(ABC):
    def get_asset_resolver_specs(self) -> list[AssetResolverSpec]:
        return []

    async def resolve_asset_refs(
        self,
        request: AssetResolveRequest,
    ) -> AssetResolveResult | dict[str, Any] | None:
        return None
```

Plugins that do not resolve assets keep the default no-op implementation.

### 6.4 Plugin Manager Dispatch

`PluginManager` should collect resolver specs from loaded plugins and dispatch
by `source_type`.

Host responsibilities:

- expose resolver specs for introspection and routing
- group incoming asset refs by `source_type`
- call the matching plugin's `resolve_asset_refs(...)`
- normalize plugin results into the host tool result contract
- merge multiple source results when one tool call resolves refs from several
  sources
- catch plugin exceptions and return partial failures without crashing the
  chat turn

Source ownership remains with plugins. The host does not inspect photo EXIF,
parse git reflogs, or understand source-specific databases beyond generic
dispatch metadata.

### 6.5 Asset Ref Contract

`asset_refs` should remain compact and safe to persist in assistant payloads.

Recommended shape:

```json
{
  "asset_ref_id": "git_session_e72de9f708_1777266361_1777269430",
  "source_type": "git_activity",
  "source_item_id": "git_session_e72de9f708_1777266361_1777269430",
  "kind": "code_activity",
  "resolver_tool": "asset_resolve",
  "resolution_state": "unresolved",
  "supported_operations": ["inspect", "files", "diff_stat"],
  "occurred_at": 1777269430,
  "attributes": {
    "repo_path": "D:\\code\\magi",
    "repo_name": "magi",
    "first_sha": "a966231e73efcab0f04043685cc58404e49f7948",
    "last_sha": "647155c9a5d95e316275c239b3aa6ebee517c0f9",
    "representative_messages": ["..."]
  }
}
```

Required fields:

- `asset_ref_id`
- `source_type`
- `kind`
- `resolver_tool="asset_resolve"` when resolvable
- `resolution_state`

Optional fields:

- `source_item_id`
- `event_id`
- `display_name`
- `captured_at` / `occurred_at`
- `supported_operations`
- sanitized `attributes`

Raw local file paths should not be stored as durable asset refs. File paths are
tool result data, used immediately by `prepare_chat_attachments` when needed.

## 7. End-to-End Flows

### 7.1 Photo Recall and Send

```text
User: "2022年9月我在哪里拍了照片"
  -> memory_query
  -> photo plugin build_recall_artifacts adds photo asset_refs
  -> assistant answers with location/session summary and persists asset_refs

User: "把刚才那些照片发出来"
  -> asset_resolve(operation="files", asset_ref_ids=[...])
  -> photo plugin returns file_paths and resolved asset_refs
  -> prepare_chat_attachments(file_paths=[...])
  -> assistant final payload includes managed attachments
```

The source-specific `photo_library_resolve_photo_refs` tool becomes an internal
resolver implementation, not an agent-visible tool.

### 7.2 Git Activity Follow-Up

```text
User: "我最近在开发什么项目"
  -> memory_query(query_mode="current_state" or activity_summary/coding_activity)
  -> git_activity recall artifact adds git_session asset_refs
  -> assistant answers "magi" and persists git asset_refs

User: "相关代码改了什么"
  -> asset_resolve(operation="diff_stat", asset_ref_ids=[git_session...])
  -> git_activity resolver runs read-only git commands in the configured repo
  -> assistant answers from changed_files, commits, and diff_stat

User: "涉及什么代码文件"
  -> asset_resolve(operation="files", asset_ref_ids=[git_session...])
  -> assistant lists verified changed files
```

`trace_query` is not used for domain asset expansion. It remains only for
runtime execution audit questions such as "what tools did you call and how long
did they take?".

## 8. Git Activity Resolver Design

### 8.1 Recall Artifact Projection

`GitActivityPlugin.build_recall_artifacts(...)` should project matching
`git_activity` L1 events into asset refs.

For session events, use provenance fields:

- `repo_path`
- `repo_name`
- `first_sha`
- `last_sha`
- `operation_counts`
- `activity_count`
- `representative_messages`
- `session_start_ts`
- `session_end_ts`

The plugin should mark the asset as:

```json
{
  "kind": "code_activity",
  "resolver_tool": "asset_resolve",
  "supported_operations": ["inspect", "files", "diff_stat"]
}
```

### 8.2 Resolver Behavior

The resolver should be read-only and bounded.

Allowed operations:

- `inspect`: return commit range, representative messages, commit list, and
  a compact summary
- `files`: return changed files with status
- `diff_stat`: return changed files plus diff stat
- `patch`: optional, disabled by default or limited to explicit user requests
  and strict size caps

Suggested git commands:

```text
git -C <repo_path> log --oneline <range>
git -C <repo_path> diff --name-status <range>
git -C <repo_path> diff --stat <range>
git -C <repo_path> diff -- <path>   # only for explicit, bounded patch requests
```

Range construction:

- Prefer `first_sha^..last_sha` when `first_sha` is a commit SHA and exists.
- Fall back to `first_sha..last_sha` if parent lookup fails.
- If only `last_sha` is present, use `git show --stat --name-status last_sha`.

Safety checks:

- Resolve `repo_path` and require it to be one of the plugin-configured repos.
- Never accept arbitrary repo paths supplied only by the LLM.
- Run only read-only git subcommands.
- Cap commit count, file count, stat text, and patch size.
- Return structured partial failure when the repo or SHAs no longer exist.

## 9. Photo Library Resolver Migration

The photo plugin should migrate from a source-specific tool to the SDK resolver
hook without losing behavior.

Current implementation:

- `get_tools()` returns `PhotoLibraryResolvePhotoRefsTool`.
- The tool scans configured photo directories and returns `file_paths`,
  `asset_refs`, `assistant_payload`, and a summary.

Target implementation:

- `get_tools()` returns no photo resolver tool.
- `get_asset_resolver_specs()` returns one spec for `source_type="photo_library"`.
- `resolve_asset_refs(...)` reuses the existing directory scan and matching
  logic.
- `build_recall_artifacts(...)` sets `resolver_tool="asset_resolve"` and
  `supported_operations=["files", "attachments"]`.

Host `asset_resolve` returns `file_paths` for `operation="files"` or
`operation="attachments"`. The existing `prepare_chat_attachments` tool remains
the only component allowed to import those paths into chat storage.

## 10. Tool Routing and Context Strategy

### 10.1 Intent Split

The router should distinguish two generic follow-up intents:

- `inspect_tool_execution`: user asks about tool calls, parameters, durations,
  or raw tool outputs. Use `trace_query`.
- `resolve_reusable_asset`: user asks to inspect, expand, send, list files, or
  explain the content behind previously returned assets. Use `asset_resolve`.

This avoids source-specific rules like "if photos then use photo resolver" or
"if git files then use git tool". The deciding signal is the presence of
reusable `asset_refs` plus a user request that refers to those assets.

### 10.2 Tool Exposure

`asset_resolve` can be a core tool, but it should be promoted only when useful:

- previous assistant payload contains reusable `asset_refs`
- recent tool state exposes asset handles
- current tool result contains `historical_recall.asset_refs`
- user explicitly supplies an `asset_ref_id`

The tool schema should remain short enough that leaving it registered globally
does not materially increase context. If later tool listing becomes dynamic,
`asset_resolve` is a good candidate for context-gated exposure.

### 10.3 External Search Fallback

Asset resolution is local evidence work. The coordinator should not append
`web-search` as a fallback for turns whose selected tools or task intent imply
`evidence_scope="local"`.

Local evidence scope includes:

- `memory_query`
- `asset_resolve`
- `trace_query`
- file/repo/code inspection tools
- `prepare_chat_attachments`

External search remains available for explicit web research or real-time public
information tasks.

## 11. Prompt and Formatting Changes

### 11.1 Memory Tool Context Formatter

When compacting `historical_recall.asset_refs`, preserve resolver capability
fields:

- `resolver_tool`
- `resolution_state`
- `supported_operations`

Without these fields, the current-turn tool context may lose the signal that an
asset can be resolved.

### 11.2 Reply Context

Reply context already preserves `resolver_tool`. It should also preserve
`supported_operations` so the next turn can choose between `files`,
`diff_stat`, and `attachments` without guessing.

### 11.3 Asset Workflow Note

The current asset workflow note focuses on sending files. It should become:

```text
If the user asks to inspect, expand, list files/changes, or send these assets,
first call `asset_resolve` with the relevant asset_ref_id(s). If the resolved
result contains file_paths and the user wants them sent in chat, then call
`prepare_chat_attachments`.
```

## 12. Security and Privacy

- Plugins may return file paths only as immediate tool result data.
- The host should sanitize assistant payloads before persistence and prompt
  reinjection.
- Source plugins must enforce their configured roots. For example, photo
  resolution stays under configured `source_paths`, and git resolution stays
  under configured `repos`.
- `asset_resolve` should be read-only. It must not run commands that mutate the
  workspace.
- Patch output must be size-capped and explicit. Default git follow-ups should
  return commits, changed files, and diff stats.
- Partial failures should be structured and answerable, not exceptions that
  force the agent to guess.

## 13. Implementation Plan

### PR-1: SDK and Host Resolver Skeleton

- Add SDK asset resolver DTOs and no-op plugin hooks.
- Re-export the DTOs from `magi_plugin_sdk` and backend compatibility imports.
- Add `PluginManager` resolver spec collection and dispatch methods.
- Add built-in `asset_resolve` tool with plugin dispatch.
- Add tests for empty resolver, missing source, partial failure, and multi-source
  merge.

### PR-2: Preserve Resolver Metadata in Memory and Chat Context

- Preserve `resolver_tool`, `resolution_state`, and `supported_operations` in
  memory compact formatting.
- Preserve `supported_operations` in reply payload summaries.
- Update asset workflow prompt note.
- Update `ContextDecider` examples from source-specific photo resolver to
  generic `asset_resolve`.

### PR-3: Photo Library Migration

- Move photo resolver logic from `photo_library_resolve_photo_refs` into
  `resolve_asset_refs(...)`.
- Keep the old tool temporarily only if a compatibility window is required;
  otherwise remove it from `get_tools()`.
- Update photo `asset_refs` to use `resolver_tool="asset_resolve"`.
- Add plugin tests for resolving known photo refs to `file_paths`.

### PR-4: Git Activity Resolver

- Add `GitActivityPlugin.build_recall_artifacts(...)`.
- Add git resolver spec and `resolve_asset_refs(...)`.
- Implement read-only, allowlisted git CLI calls.
- Add tests for `inspect`, `files`, `diff_stat`, missing repo, invalid SHA, and
  path allowlist enforcement.

### PR-5: Local Evidence Fallback Policy

- Replace unconditional web-search fallback with evidence-scope-aware fallback.
- Ensure `asset_resolve`, `memory_query`, and `trace_query` do not trigger
  external search unless the user explicitly asks for web research.

## 14. Validation

Backend validation:

- Unit tests for SDK DTO validation.
- Unit tests for `PluginManager` resolver dispatch.
- Tool tests for `asset_resolve` result merging and errors.
- Chat routing tests for reusable asset follow-up vs runtime trace follow-up.
- Memory formatting tests that resolver metadata survives compaction.

Plugin validation:

- Photo plugin resolves representative photo refs to local paths and then
  `prepare_chat_attachments` can import those paths.
- Git plugin resolves a temporary repository session into commits, changed
  files, and diff stats.
- Git resolver rejects repos outside configured plugin settings.

Manual replay:

1. Ask "2022年9月我在哪里拍了照片" with photo-library enabled.
2. Ask "把刚才那些照片发出来" and verify the tool chain is
   `asset_resolve -> prepare_chat_attachments`.
3. Ask "我最近在开发什么项目" with git_activity enabled.
4. Ask "相关代码改了什么" and verify `asset_resolve` returns git evidence.
5. Ask "刚刚你调了什么工具，参数和耗时是多少" and verify `trace_query` is
   selected, not `asset_resolve`.

## 15. Migration Compatibility

During migration, the host may support both forms:

- generic `asset_resolve`
- legacy source-specific resolver tools already contributed by plugins

The preferred end state is that source-specific resolver tools are removed from
the agent-visible list. If compatibility is needed, legacy tools should be
marked deprecated in metadata and excluded from high-level routing examples.

Plugin authors should treat `build_recall_artifacts(...)` plus
`resolve_asset_refs(...)` as the canonical asset recall path.

## 16. Open Questions

- Whether `patch` should be disabled globally until the git resolver has
  stronger output caps and redaction.
- Whether `asset_resolve` should accept only `asset_ref_ids` and look up full
  refs from recent assistant payloads, or continue accepting full `asset_refs`
  for stateless worker contexts.
- Whether resolver specs should appear in plugin contribution APIs so the
  frontend can show which sources support asset follow-up actions.

These questions do not block PR-1 through PR-3. They can be resolved before the
git patch operation or frontend introspection work ships.
