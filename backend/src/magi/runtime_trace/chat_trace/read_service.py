"""Read-side aggregation service for per-turn execution traces."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional

from ...core.logger import get_logger
from ...utils.runtime import get_runtime_paths
from .constants import (
    TRACE_NODE_EVENT_TYPES,
)
from .models import (
    ExecutionTraceNode,
)
from .runtime_rows import TraceRuntimeRowsMixin
from .snapshot_builder import TraceSnapshotBuilderMixin
from .builders.normalized import (
    build_trace_span_node,
    collapse_trace_spans,
    merge_trace_payload,
)
from .builders.rows import (
    build_trace_row_node,
    resolve_result_preview,
)
from .tree import build_runtime_trace_root, deduplicate_response_emit, with_dispatch_label
from .utils import (
    compact_value,
    default_trace_label,
    is_terminal_status,
    map_trace_kind,
    ms_to_seconds,
    normalize_status,
    optional_text,
    parse_json_object,
    parse_json_value,
    safe_int,
    tool_event_arguments,
    tool_event_result_preview,
    tool_event_status,
    trace_span_error,
    trace_span_result_preview,
)

logger = get_logger(__name__)


class ChatTraceReadService(TraceSnapshotBuilderMixin, TraceRuntimeRowsMixin):
    """Build per-turn execution snapshots from persisted runtime events."""

    def __init__(self) -> None:
        runtime_paths = get_runtime_paths()
        self._l1_db_path: Path = runtime_paths.l1_memory_db_path
        self._runtime_trace_db_path: Path = runtime_paths.runtime_trace_db_path

    def get_trace_snapshot(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
    ) -> Optional[dict[str, Any]]:
        normalized_turn_id = str(turn_id or "").strip()
        if not normalized_turn_id:
            return None
        turn = self._load_trace_turn(user_id=user_id, session_id=session_id, turn_id=normalized_turn_id)
        if turn is None:
            return None
        spans = self._load_trace_spans(trace_id=str(turn.get("trace_id") or ""))
        llm_calls = self._load_detail_rows(table="trace_llm_calls", trace_id=str(turn.get("trace_id") or ""))
        tool_calls = self._load_detail_rows(table="trace_tools", trace_id=str(turn.get("trace_id") or ""))
        intent_resolutions = self._load_detail_rows(table="trace_intent_resolutions", trace_id=str(turn.get("trace_id") or ""))
        snapshot = self._build_snapshot_from_trace_rows(
            user_id=user_id,
            session_id=session_id,
            turn=turn,
            spans=spans,
            llm_calls=llm_calls,
            tool_calls=tool_calls,
            intent_resolutions=intent_resolutions,
            orchestration_state=None,
        )
        return snapshot.to_dict() if snapshot is not None else None

    def get_trace_summary(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
    ) -> Optional[dict[str, Any]]:
        snapshot = self.get_trace_snapshot(user_id=user_id, session_id=session_id, turn_id=turn_id)
        if not isinstance(snapshot, dict):
            return None
        summary = snapshot.get("summary")
        return summary if isinstance(summary, dict) else None

    async def aget_trace_snapshot(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
    ) -> Optional[dict[str, Any]]:
        """Build a trace snapshot without blocking the event loop."""
        return await asyncio.to_thread(
            self.get_trace_snapshot,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
        )

    async def aget_trace_summary(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
    ) -> Optional[dict[str, Any]]:
        """Build a trace summary without blocking the event loop."""
        return await asyncio.to_thread(
            self.get_trace_summary,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
        )

    async def aget_turn_activity_map(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> dict[str, dict[str, Any]]:
        """Build turn activity without blocking the event loop."""
        return await asyncio.to_thread(
            self.get_turn_activity_map,
            user_id=user_id,
            session_id=session_id,
        )

    def get_turn_activity_map(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> dict[str, dict[str, Any]]:
        activity: dict[str, dict[str, Any]] = {}
        for turn in self._load_session_turns(user_id=user_id, session_id=session_id):
            turn_id = str(turn.get("turn_id") or "").strip()
            summary = self.get_trace_summary(user_id=user_id, session_id=session_id, turn_id=turn_id)
            if summary is not None:
                activity[turn_id] = summary
        return activity

    def _build_runtime_trace_root(
        self,
        *,
        turn: dict[str, Any],
        spans: list[dict[str, Any]],
        llm_calls: list[dict[str, Any]],
        tool_calls: list[dict[str, Any]],
        intent_resolutions: list[dict[str, Any]],
    ) -> ExecutionTraceNode:
        return build_runtime_trace_root(
            turn=turn,
            spans=spans,
            llm_calls=llm_calls,
            tool_calls=tool_calls,
            intent_resolutions=intent_resolutions,
        )

    def _with_dispatch_label(self, node: ExecutionTraceNode) -> ExecutionTraceNode:
        return with_dispatch_label(node)

    @staticmethod
    def _deduplicate_response_emit(root: ExecutionTraceNode) -> None:
        """Remove the response_emit node when its content duplicates the last iteration."""
        deduplicate_response_emit(root)

    def _build_trace_row_node(
        self,
        *,
        span: dict[str, Any],
        llm_call: dict[str, Any] | None,
        tool_call: dict[str, Any] | None,
        intent_resolution: dict[str, Any] | None = None,
    ) -> ExecutionTraceNode:
        return build_trace_row_node(
            span=span,
            llm_call=llm_call,
            tool_call=tool_call,
            intent_resolution=intent_resolution,
        )

    @staticmethod
    def _resolve_result_preview(
        *,
        span: dict[str, Any],
        llm_call: dict[str, Any] | None,
        tool_call: dict[str, Any] | None,
    ) -> str:
        return resolve_result_preview(span=span, llm_call=llm_call, tool_call=tool_call)

    @staticmethod
    def _parse_json_object(raw_value: Any) -> dict[str, Any]:
        return parse_json_object(raw_value)

    @staticmethod
    def _parse_json_value(raw_value: Any) -> Any:
        return parse_json_value(raw_value)

    def _collapse_trace_spans(self, events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return collapse_trace_spans(events, trace_node_event_types=TRACE_NODE_EVENT_TYPES)

    def _merge_trace_payload(self, current: dict[str, Any], incoming: dict[str, Any]) -> None:
        merge_trace_payload(current, incoming)

    def _build_trace_span_node(self, payload: dict[str, Any]) -> ExecutionTraceNode:
        return build_trace_span_node(payload)

    def _map_trace_kind(self, node_type: str) -> str:
        return map_trace_kind(node_type)

    def _default_trace_label(self, node_type: str) -> str:
        return default_trace_label(node_type)

    def _trace_span_result_preview(self, payload: dict[str, Any]) -> str:
        return trace_span_result_preview(payload)

    def _trace_span_error(self, payload: dict[str, Any]) -> Optional[str]:
        return trace_span_error(payload)

    def _ms_to_seconds(self, value: Any) -> Optional[float]:
        return ms_to_seconds(value)

    def _tool_event_status(self, payload: dict[str, Any]) -> str:
        return tool_event_status(payload)

    def _tool_event_result_preview(self, payload: dict[str, Any]) -> str:
        return tool_event_result_preview(payload)

    def _tool_event_arguments(self, payload: dict[str, Any]) -> dict[str, Any]:
        return tool_event_arguments(payload)

    def _normalize_status(self, status: str) -> str:
        return normalize_status(status)

    @staticmethod
    def _is_terminal_status(status: str) -> bool:
        return is_terminal_status(status)

    @staticmethod
    def _optional_text(value: Any) -> Optional[str]:
        return optional_text(value)

    def _compact_value(self, value: Any) -> str:
        return compact_value(value)

    def _safe_int(self, value: Any, *, default: int) -> int:
        return safe_int(value, default=default)


def get_chat_trace_read_service() -> ChatTraceReadService:
    """Get the shared ChatTraceReadService instance."""
    from .provider import (
        get_chat_trace_read_service as _get_chat_trace_read_service,
    )

    return _get_chat_trace_read_service()
