"""Host-only tool context shared by operation admission and bundled tools."""

from collections.abc import Callable
from typing import Any

from pydantic import Field, InstanceOf
from magi_plugin_sdk.capabilities import HostMethod
from magi_plugin_sdk.tools import ToolExecutionContext as PublicToolExecutionContext

from .tool_capabilities import ToolCapabilities


class ToolExecutionContext(PublicToolExecutionContext):
    """Keep live service handles and authorization outside the public SDK."""

    capabilities: InstanceOf[ToolCapabilities] | None = Field(default=None, exclude=True)
    cancellation: Any = Field(default=None, exclude=True)
    trace_context: Any = Field(default=None, exclude=True)
    host_service_grants: frozenset[HostMethod] = Field(default_factory=frozenset, exclude=True)
    host_service_authorize: Callable[[HostMethod], bool] | None = Field(default=None, exclude=True)


__all__ = ["ToolExecutionContext"]
