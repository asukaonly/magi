"""Phase F: typed conversation content + events."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class ContentBlock:
    """One typed fragment of a message.

    Phase F scope: ``kind="text"`` only. Phase I extends with
    ``image`` / ``code`` / ``tool_use`` / ``file`` variants.
    """
    kind: Literal["text"]
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "text": self.text, "metadata": dict(self.metadata)}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ContentBlock":
        return cls(
            kind=d.get("kind", "text"),
            text=str(d.get("text", "")),
            metadata=dict(d.get("metadata") or {}),
        )


__all__ = ["ContentBlock"]
