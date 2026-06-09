"""Re-export shim — canonical implementation in magi_plugin_sdk.workspace_cache."""
from magi_plugin_sdk.workspace_cache.root import *  # noqa: F401, F403
from magi_plugin_sdk.workspace_cache.root import WorkspaceCacheRoot

__all__ = ["WorkspaceCacheRoot"]
