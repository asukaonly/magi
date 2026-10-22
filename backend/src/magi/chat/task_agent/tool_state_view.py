"""Bounded per-session tool context updated by chat postprocessing.

Durable execution evidence remains owned by runtime_trace. This cache only
contains interactions observed by the current chat runtime and never opens
another domain's storage.
"""

from __future__ import annotations

from typing import Any


# Fields harvested out of ``result_data`` for the LLM to reuse as
# handles in the next turn (e.g. "I just stored attachment_id=foo,
# you can reference it"). Probed recursively up to depth 3.
_TOOL_STATE_HANDLE_FIELDS = (
    "attachment_id",
    "asset_ref_id",
    "event_id",
    "entity_id",
    "task_id",
    "worker_id",
    "source_item_id",
    "message_id",
)

# Per-session record retention. Bounded so a long session does not
# grow memory unbounded; the LLM only ever asks for the most recent
# few via :py:meth:`recent_errors` / :py:meth:`recent_state`.
_MAX_RECORDS_PER_SESSION = 100

class ChatToolStateView:
    """Per-session recent-tool-call view used by chat prompt assembly.

    Keyed by ``history_key`` (``user_id::session_id``), matching the
    convention used elsewhere in the chat task agent.
    """

    def __init__(self) -> None:
        self._records: dict[str, list[dict[str, Any]]] = {}

    # === writes ===

    def record(self, history_key: str, record: dict[str, Any]) -> None:
        """Append one tool interaction; trim to the rolling window."""
        records = self._records.setdefault(history_key, [])
        records.append(record)
        if len(records) > _MAX_RECORDS_PER_SESSION:
            self._records[history_key] = records[-_MAX_RECORDS_PER_SESSION:]

    def clear(self, history_key: str) -> None:
        """Drop all records for a session (used on conversation reset)."""
        self._records[history_key] = []

    def evict(self, history_key: str) -> None:
        """Remove a session entirely (used by the LRU eviction path)."""
        self._records.pop(history_key, None)

    # === reads (prompt-shaped) ===

    def recent_errors(self, history_key: str, limit: int = 3) -> list[dict[str, Any]]:
        """Most recent error tool calls, newest first, shaped for prompt use."""
        records = self._records.get(history_key, [])
        results: list[dict[str, Any]] = []
        for item in reversed(records):
            if str(item.get("status") or "") != "error":
                continue
            result_data = item.get("result_data")
            config_path: str | None = None
            next_action: str | None = None
            if isinstance(result_data, dict):
                raw_path = result_data.get("config_path")
                if raw_path is not None:
                    config_path = str(raw_path).strip() or None
                raw_action = result_data.get("next_action")
                if raw_action is not None:
                    next_action = str(raw_action).strip() or None
            results.append(
                {
                    "tool_name": str(item.get("tool_name") or "unknown"),
                    "error_code": str(item.get("error_code") or "UNKNOWN"),
                    "error_message": str(item.get("error_message") or ""),
                    "config_path": config_path,
                    "next_action": next_action,
                }
            )
            if len(results) >= max(1, limit):
                break
        return results

    def recent_state(self, history_key: str, limit: int = 4) -> list[dict[str, Any]]:
        """Most recent tool calls, newest first, shaped for prompt use.

        Returns one dict per call summarising tool, status, optional
        error code/message, outcome summary, execution time, and any
        reusable handles harvested from the tool's result_data.
        """
        records = self._records.get(history_key, [])
        results: list[dict[str, Any]] = []
        for item in reversed(records):
            if not isinstance(item, dict):
                continue
            tool_name = str(item.get("tool_name") or "").strip()
            if not tool_name:
                continue
            status = str(item.get("status") or "unknown").strip() or "unknown"
            result_summary = str(item.get("result_summary") or "").strip()
            result_data = (
                item.get("result_data") if isinstance(item.get("result_data"), dict) else {}
            )
            state: dict[str, Any] = {
                "tool_name": tool_name,
                "status": status,
            }
            turn_id = str(item.get("turn_id") or "").strip()
            if turn_id:
                state["turn_id"] = turn_id
            execution_time_ms = _normalize_execution_time_ms(item.get("execution_time_ms"))
            if execution_time_ms is not None:
                state["execution_time_ms"] = execution_time_ms
            if result_summary:
                state["outcome"] = result_summary[:160]
            if status != "success":
                error_code = str(item.get("error_code") or "").strip()
                error_message = str(item.get("error_message") or "").strip()
                if error_code:
                    state["error_code"] = error_code
                if error_message:
                    state["error_message"] = error_message[:160]
            handles = _extract_reusable_handles(result_data)
            if handles:
                state["handles"] = handles
            results.append(state)
            if len(results) >= max(1, limit):
                break
        return results

def _normalize_execution_time_ms(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        normalized = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return max(0, normalized)


def _extract_reusable_handles(result_data: dict[str, Any]) -> list[str]:
    """Walk ``result_data`` up to depth 3 and pull out reusable handles.

    Handles are short ``field:value`` strings the LLM can reference in
    the next turn ("you have task_id:abc123 active"). Capped at 6 per
    call to keep prompt size bounded.
    """
    handles: list[str] = []

    def _visit(value: Any, *, depth: int) -> None:
        if depth > 3:
            return
        if isinstance(value, dict):
            for field_name in _TOOL_STATE_HANDLE_FIELDS:
                nested_value = value.get(field_name)
                if nested_value is None:
                    continue
                text = str(nested_value).strip()
                if text:
                    handles.append(f"{field_name}:{text}")
            for nested in value.values():
                _visit(nested, depth=depth + 1)
            return
        if isinstance(value, list):
            for item in value[:3]:
                _visit(item, depth=depth + 1)

    _visit(result_data, depth=0)

    deduped: list[str] = []
    seen: set[str] = set()
    for handle in handles:
        if handle in seen:
            continue
        seen.add(handle)
        deduped.append(handle)
        if len(deduped) >= 6:
            break
    return deduped
