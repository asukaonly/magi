"""Provider-neutral model-context records owned by the chat domain."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from magi.utils.model_context_messages import set_runtime_message_provenance
from magi.utils.tool_result_metadata import TOOL_RESULT_METADATA_KEY, ToolResultMetadata

from magi_plugin_sdk.storage_models.chat_model_context import (
    ModelContextItemKind,
    ModelContextScope,
    ModelContextItem,
    ModelContextEvent,
    ModelContextSnapshot,
    ModelContextEpoch,
    ModelContextBoundary,
    ModelContextCallSnapshot,
    ModelContextRevisionConflictError,
    ModelContextRunClosedError,
    infer_model_context_item_kind,
)
























__all__ = [
    "ModelContextBoundary",
    "ModelContextCallSnapshot",
    "ModelContextEpoch",
    "ModelContextEvent",
    "ModelContextItem",
    "ModelContextItemKind",
    "ModelContextRevisionConflictError",
    "ModelContextRunClosedError",
    "ModelContextScope",
    "ModelContextSnapshot",
    "infer_model_context_item_kind",
]
