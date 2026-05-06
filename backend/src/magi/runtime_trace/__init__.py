"""Runtime trace persistence package.

The persisted ingress row dataclass is exported as
``StoredPluginIngressEventRecord``. The SDK-facing Protocol lives in
``magi_plugin_sdk.ingress`` and should be imported from there directly.
"""

from .contracts import (
    PluginIngressEventRecord as StoredPluginIngressEventRecord,
    RuntimeHeartbeatRecord,
    RuntimeNotificationRecord,
    TraceIntentResolutionRecord,
    TraceLlmCallRecord,
    TraceSpanRecord,
    TraceToolRecord,
    TraceTurnRecord,
)
from .store import RuntimeTraceStore

__all__ = [
    "RuntimeTraceStore",
    "StoredPluginIngressEventRecord",
    "RuntimeHeartbeatRecord",
    "RuntimeNotificationRecord",
    "TraceTurnRecord",
    "TraceSpanRecord",
    "TraceIntentResolutionRecord",
    "TraceLlmCallRecord",
    "TraceToolRecord",
]
