"""Re-export shim — canonical implementation in magi_plugin_sdk.workspace_cache."""
from magi_plugin_sdk.workspace_cache._resolver import *  # noqa: F401, F403
from magi_plugin_sdk.workspace_cache._resolver import resolve_session_cache

__all__ = ["resolve_session_cache"]
