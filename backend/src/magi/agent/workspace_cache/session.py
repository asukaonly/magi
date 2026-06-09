"""Re-export shim — canonical implementation in magi_plugin_sdk.workspace_cache."""
from magi_plugin_sdk.workspace_cache.session import *  # noqa: F401, F403
from magi_plugin_sdk.workspace_cache.session import SessionCache

__all__ = ["SessionCache"]
