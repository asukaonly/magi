"""Runtime trace persistence package.

`PluginIngressEventRecord` is re-exported here as the SDK-facing ingress event
protocol for compatibility with older plugin code that typed handlers against
`magi.runtime_trace`. Backend code that needs the persisted row model should use
`StoredPluginIngressEventRecord` or import directly from `.contracts`.
"""

from magi_plugin_sdk.ingress import PluginIngressEventRecord

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
    "PluginIngressEventRecord",
    "StoredPluginIngressEventRecord",
    "RuntimeHeartbeatRecord",
    "RuntimeNotificationRecord",
    "TraceTurnRecord",
    "TraceSpanRecord",
    "TraceIntentResolutionRecord",
    "TraceLlmCallRecord",
    "TraceToolRecord",
]
