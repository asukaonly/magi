# Memory Tool Context Formatting Design

## Goal

Reduce the amount of memory tool output that is injected back into the main LLM during function calling, without changing the raw retrieval payload returned by the memory stack itself.

## Problem

`memory_query` currently returns rich retrieval payloads that are useful for debugging and API inspection, but too verbose for tool-message context. The function-calling loop feeds those payloads back to the main LLM as JSON, including many internal fields such as:

- `event_id`
- `correlation_id`
- `created_at`
- `retention_class`
- `tom_depth`

These fields increase token usage but rarely improve answer quality for the main LLM.

## Design

### Boundary

- Keep raw retrieval payloads unchanged in `memory_query_tool`
- Compact only the tool-message payload injected back into the main LLM
- Put memory-specific compaction logic in the memory layer, not in the function-calling executor

### Structure

1. `FunctionCallingPostprocessor` becomes a dispatcher over tool-specific compactors.
2. `memory_query` gets its own formatter in the memory package.
3. Existing compactors for `glob`, `bash`, `grep`, `file_read`, and `agent` remain behavior-compatible for now.

### Memory formatter output

Keep only answer-relevant fields:

- `l1_events`
  - `session_id`
  - `turn_id`
  - `timestamp`
  - `author_type`
  - `event_type`
  - `score`
  - `content_preview`
  - `content_truncated`
- `l1_timeline_summary`
  - `session_id`
  - `turn_id`
  - `timestamp`
  - `author_type`
  - `summary_preview`
  - `summary_truncated`
- `meta`
  - compact retrieval trace fields only

Drop internal storage and cognition fields that are not useful to the main LLM.

## Non-Goals

- Do not change the retrieval service contract.
- Do not change API-level eval payloads.
- Do not redesign all tool compactors in one pass.

## Migration Path

This change establishes an extension point:

- future complex tools can move their context-formatting logic into their owning domain
- `FunctionCallingPostprocessor` can shrink toward a dispatcher plus generic fallback behavior
