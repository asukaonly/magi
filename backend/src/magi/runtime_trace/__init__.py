"""Runtime trace persistence package.

The persisted ingress row dataclass is exported as
``StoredPluginIngressEventRecord``. The SDK-facing Protocol lives in
``magi_plugin_sdk.ingress`` and should be imported from there directly.
"""

from .contracts import (
    PluginIngressEventRecord as StoredPluginIngressEventRecord,
    RuntimeNotificationRecord,
    TraceIntentResolutionRecord,
    TraceLlmCallRecord,
    TraceSpanRecord,
    TraceToolRecord,
    TraceTurnRecord,
)
from .store import RuntimeTraceStore
from .writer import RuntimeTraceWriter
from .ids import (
    build_root_span_id,
    build_trace_id,
    enrich_event_context_with_turn_trace,
    normalize_turn_id,
)

__all__ = [
    "RuntimeTraceStore",
    "RuntimeTraceWriter",
    "build_root_span_id",
    "build_trace_id",
    "enrich_event_context_with_turn_trace",
    "normalize_turn_id",
    "StoredPluginIngressEventRecord",
    "RuntimeNotificationRecord",
    "TraceTurnRecord",
    "TraceSpanRecord",
    "TraceIntentResolutionRecord",
    "TraceLlmCallRecord",
    "TraceToolRecord",
]
