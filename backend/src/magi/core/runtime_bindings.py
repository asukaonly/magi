"""The command queue and agent-runtime boundary roots."""
from __future__ import annotations
from typing import Any
from .container import optional_binding, require_binding


def require_runtime_command_queue() -> Any:
    return require_binding("runtime_command_queue")


def require_agent_runtime() -> Any:
    return require_binding("agent_runtime")


def get_optional_agent_runtime() -> Any | None:
    return optional_binding("agent_runtime")
