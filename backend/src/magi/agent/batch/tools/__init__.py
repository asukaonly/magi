"""Host batch runtime-control tools (L12).

These tools are part of the agent *runtime*, not plugin-contributed
capabilities: their ``execute()`` orchestrates host machinery (the batch
store/driver and the background task manager) — something a sandboxable plugin
must never do. Like ``magi.agent.runtime_tools.agent_tool``, they therefore
live above the L8 tool registry inside the agent layer and are registered into
the runtime ``tool_registry`` from the composition root — see
``magi.bootstrap.runtime_tools`` — rather than via the plugin surface.
"""

from __future__ import annotations

from .batch_create_tool import BatchCreateTool
from .batch_item_update_tool import BatchItemUpdateTool
from .batch_review_tool import BatchReviewTool

# First-party batch runtime tool classes that the composition root host-registers.
BATCH_TOOL_CLASSES: tuple[type, ...] = (
    BatchCreateTool,
    BatchItemUpdateTool,
    BatchReviewTool,
)

__all__ = [
    "BATCH_TOOL_CLASSES",
    "BatchCreateTool",
    "BatchItemUpdateTool",
    "BatchReviewTool",
]
