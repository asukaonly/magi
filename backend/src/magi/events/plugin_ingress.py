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


class PluginIngressRegistry:
    """Live handler catalog shared by admission and processing."""

    def __init__(self) -> None:
        self.entries: dict[tuple[str, str], PluginIngressHandlerRegistration] = {}
        self.ready = False

    def accepts_delivery(self, target: str, event_type: str) -> bool:
        entry = self.entries.get((target, event_type))
        return entry is not None and entry.replay_safe
