"""Host runtime tools (L12).

Tools in this package are part of the agent *runtime*, not plugin-contributed
capabilities. They live above the L8 tool registry because they reach into the
agent layer (e.g. spawning sub-agents via ``magi.agent.workers``) — something a
plugin must never do recursively.

Because this package sits above the tool registry, the L8 tool plumbing
(``magi.tools.core_tools`` / ``magi.tools.lifecycle``) cannot import it. These
classes are registered into the runtime ``tool_registry`` from the composition
root instead — see ``magi.bootstrap.runtime_tools``.
"""

from __future__ import annotations

from .agent_tool import (
    AgentTool,
    WorkerRunState,
)

# First-party runtime tool classes that the composition root host-registers.
AGENT_RUNTIME_TOOL_CLASSES: tuple[type, ...] = (AgentTool,)

__all__ = [
    "AGENT_RUNTIME_TOOL_CLASSES",
    "AgentTool",
    "WorkerRunState",
]
