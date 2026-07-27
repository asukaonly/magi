"""Contracts for prompt-facing L0 projections."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class L0PromptWorkbenchProjection:
    """Prompt-facing session attention payload."""

    session: dict[str, Any] | None
    attention_items: list[Any] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        """Return a JSON-serializable payload for retrieval and prompt assembly."""
        return asdict(self)

    def to_retrieval_entry(self) -> dict[str, Any]:
        """Return the retrieval-facing L0 workbench entry shape."""
        payload = self.to_payload()
        return {
            "session": payload.get("session"),
            "attention_items": payload.get("attention_items", []),
        }
