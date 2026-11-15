"""Runtime-only tool status used independently of model observation text."""

from __future__ import annotations

from magi_plugin_sdk.storage_models.tool_result_metadata import (
    TOOL_RESULT_METADATA_KEY as TOOL_RESULT_METADATA_KEY,
    ToolResultMetadata as ToolResultMetadata,
    tool_result_metadata as tool_result_metadata,
    strip_tool_result_metadata as strip_tool_result_metadata,
)
