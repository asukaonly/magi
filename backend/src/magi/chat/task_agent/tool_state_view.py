"""Chat-domain per-session view over recent tool interactions.

This is the chat driver's read view (ADR-0004 ring 3) over the
``runtime_trace`` tool-call stream. It is *not* the source of truth —
that's the ``trace_tools`` SQLite table in ``runtime_trace`` (L1).
``ChatToolStateView`` holds a per-session in-memory cache hydrated
on startup from ``runtime_trace`` and updated by chat postprocess as
new tool calls land, and exposes two prompt-shaped readers used when
chat assembles its LLM context: "recent tool errors" and
"recent tool state".

Layering note: this is per-session state belonging to the chat
domain (L14). Lifting it to the generic agent runtime (L12) would be
premature — only chat reads it today. If worker / subagent / batch
drivers later need an equivalent, promote the shape then.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from magi.core.logger import get_logger
from magi.core.sqlite import connect_sqlite

logger = get_logger(__name__)


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

# Recovery scan size on cold start. Chosen to cover several days of
# normal usage without scanning unbounded history.
_RESTORE_SCAN_LIMIT = 5000


class ChatToolStateView:
    """Per-session recent-tool-call view used by chat prompt assembly.

    Keyed by ``history_key`` (``user_id::session_id``), matching the
    convention used elsewhere in the chat task agent.
    """

    def __init__(self, *, runtime_trace_db_path: Path) -> None:
        self._runtime_trace_db_path = runtime_trace_db_path
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

    def recent_errors(
        self, history_key: str, limit: int = 3
    ) -> list[dict[str, Any]]:
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

    def recent_state(
        self, history_key: str, limit: int = 4
    ) -> list[dict[str, Any]]:
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
                item.get("result_data")
                if isinstance(item.get("result_data"), dict)
                else {}
            )
            state: dict[str, Any] = {
                "tool_name": tool_name,
                "status": status,
            }
            turn_id = str(item.get("turn_id") or "").strip()
            if turn_id:
                state["turn_id"] = turn_id
            execution_time_ms = _normalize_execution_time_ms(
                item.get("execution_time_ms")
            )
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

    # === lifecycle ===

    def restore_from_trace(
        self,
        *,
        require_session_id: Callable[[str, Any], str],
        build_history_key: Callable[[str, str], str],
    ) -> None:
        """Re-hydrate the in-memory cache from ``runtime_trace``.

        Called once at chat agent startup. ``require_session_id`` and
        ``build_history_key`` are passed in rather than imported so this
        module does not depend on ChatHistoryService's helpers (and so
        the keying convention stays a single source of truth on
        ChatHistoryService).
        """
        try:
            if not self._runtime_trace_db_path.exists():
                return
            conn = connect_sqlite(
                self._runtime_trace_db_path,
                profile="hot_write",
                use_row_factory=False,
            )
            cur = conn.cursor()
            cur.execute(
                """
                SELECT
                    trace_turns.user_id,
                    trace_turns.session_id,
                    trace_tools.turn_id,
                    trace_tools.tool_name,
                    trace_tools.error_code,
                    trace_tools.error_message,
                    trace_tools.result_preview,
                    trace_tools.arguments_json,
                    trace_tools.execution_time_ms,
                    trace_tools.success
                FROM trace_tools
                JOIN trace_turns ON trace_turns.trace_id = trace_tools.trace_id
                ORDER BY trace_turns.updated_at_ms ASC
                LIMIT ?
                """,
                (_RESTORE_SCAN_LIMIT,),
            )
            rows = cur.fetchall()
            conn.close()
        except Exception:
            logger.warning(
                "Failed to restore tool interactions from runtime trace store"
            )
            return

        for (
            user_id,
            raw_session_id,
            turn_id,
            tool_name,
            error_code,
            error_message,
            result_preview,
            arguments_json,
            execution_time_ms,
            success,
        ) in rows:
            if not user_id:
                continue
            session_id = require_session_id(str(user_id), raw_session_id)
            key = build_history_key(str(user_id), session_id)
            result_data: dict[str, Any] = {}
            try:
                parsed = json.loads(str(arguments_json or ""))
                if isinstance(parsed, dict):
                    result_data = parsed
            except Exception:
                result_data = {}
            self.record(
                key,
                {
                    "timestamp": execution_time_ms,
                    "intent": "unknown",
                    "tool_name": str(tool_name or "unknown"),
                    "status": "success" if bool(success) else "error",
                    "error_code": str(error_code or ""),
                    "error_message": str(error_message or ""),
                    "result_summary": str(result_preview or ""),
                    "result_data": result_data,
                    "execution_time_ms": _normalize_execution_time_ms(
                        execution_time_ms
                    ),
                    "turn_id": turn_id,
                },
            )


# === module helpers ===


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
