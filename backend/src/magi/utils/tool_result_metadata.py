"""Runtime-only tool status used independently of model observation text."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from magi_plugin_sdk.storage_models.tool_result_metadata import (
    TOOL_RESULT_METADATA_KEY,
    ToolResultMetadata,
    tool_result_metadata,
    strip_tool_result_metadata,
)
