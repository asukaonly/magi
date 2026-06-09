"""Runtime trace and notification facade for chat post-processing."""

from __future__ import annotations

from .trace_llm import ChatPostprocessLlmTraceMixin
from .trace_notifications import ChatPostprocessTraceNotificationMixin
from .trace_runtime import ChatPostprocessRuntimeTraceMixin
from .utils import (
    build_root_span_id,
    build_span_id,
    build_trace_id,
    normalize_mode,
    resolve_started_at_ms,
    serialize_ux_plan,
)


class ChatPostprocessTraceMixin(
    ChatPostprocessRuntimeTraceMixin,
    ChatPostprocessTraceNotificationMixin,
    ChatPostprocessLlmTraceMixin,
):
    """Persist chat runtime traces and emit runtime notifications."""

    _build_trace_id = staticmethod(build_trace_id)
    _build_root_span_id = staticmethod(build_root_span_id)
    _build_span_id = staticmethod(build_span_id)
    _serialize_ux_plan = staticmethod(serialize_ux_plan)
    _resolve_started_at_ms = staticmethod(resolve_started_at_ms)
    _normalize_mode = staticmethod(normalize_mode)


__all__ = ["ChatPostprocessTraceMixin"]
