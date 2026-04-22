"""Plugin ingress contracts - re-exported from magi-plugin-sdk."""

from magi_plugin_sdk.ingress import (  # noqa: F401
    PluginIngressEventHandler,
    PluginIngressEventRecord,
    PluginIngressHandlerRegistration,
)

__all__ = [
    "PluginIngressEventHandler",
    "PluginIngressEventRecord",
    "PluginIngressHandlerRegistration",
]
