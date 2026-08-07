"""Phase 2 language-synthesis contracts for L2 memory."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class L2Phase2Summary:
    """Optional user-facing wording for one host-owned materialization target."""

    claim_ids: list[str] = field(default_factory=list)
    text: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "L2Phase2Summary":
        return cls(
            claim_ids=payload.get("claim_ids", []),
            text=str(payload.get("text", "") or "")[:500],
        )

    def __post_init__(self) -> None:
        self.claim_ids = _unique_texts(self.claim_ids)
        self.text = " ".join(str(self.text or "").split())[:500]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2Phase2Result:
    """Optional Phase 2 wording result with no semantic authority."""

    summaries: list[L2Phase2Summary] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "L2Phase2Result":
        return cls(
            summaries=[
                L2Phase2Summary.from_dict(item)
                for item in payload.get("summaries", [])
                if isinstance(item, dict)
            ]
        )

    def __post_init__(self) -> None:
        self.summaries = [
            item if isinstance(item, L2Phase2Summary) else L2Phase2Summary.from_dict(item)
            for item in self.summaries
            if isinstance(item, (L2Phase2Summary, dict))
        ]

    def to_dict(self) -> dict[str, Any]:
        return {"summaries": [item.to_dict() for item in self.summaries]}

    @property
    def has_content(self) -> bool:
        return bool(self.summaries)


def _unique_texts(values: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        unique.append(text)
    return unique


__all__ = ["L2Phase2Result", "L2Phase2Summary"]
