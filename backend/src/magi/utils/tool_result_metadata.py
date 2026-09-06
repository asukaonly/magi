"""Runtime-only tool status used independently of model observation text."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


TOOL_RESULT_METADATA_KEY = "_magi_tool_result"


@dataclass(frozen=True, slots=True)
class ToolResultMetadata:
    """Small replayable status; full execution evidence stays in the journal."""

    success: bool
    summary: str
    evidence_ref: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Any) -> ToolResultMetadata | None:
        if not isinstance(value, Mapping) or not isinstance(value.get("success"), bool):
            return None
        if not isinstance(value.get("summary"), str) or not isinstance(value.get("evidence_ref"), str):
            return None
        return cls(value["success"], value["summary"], value["evidence_ref"])


def tool_result_metadata(message: Mapping[str, Any]) -> ToolResultMetadata | None:
    """Read host-produced status without interpreting external result text."""
    return ToolResultMetadata.from_dict(message.get(TOOL_RESULT_METADATA_KEY))


def strip_tool_result_metadata(message: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in message.items() if key != TOOL_RESULT_METADATA_KEY}
