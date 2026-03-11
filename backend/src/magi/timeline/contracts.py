"""Timeline domain contracts."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass(slots=True)
class TimelineContentBlock:
    """Normalized content block for timeline events."""

    kind: str
    value: str
    mime_type: Optional[str] = None


@dataclass(slots=True)
class TimelineEvent:
    """Canonical timeline fact payload stored in L1."""

    event_id: str
    source_type: str
    source_item_id: str
    occurred_at: float
    captured_at: float
    title: str
    summary: str
    retention_mode: str
    raw_payload_ref: Optional[str] = None
    content_blocks: list[TimelineContentBlock] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    privacy_labels: list[str] = field(default_factory=list)
    processing_status: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["content_blocks"] = [asdict(block) for block in self.content_blocks]
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TimelineEvent":
        return cls(
            event_id=str(payload["event_id"]),
            source_type=str(payload["source_type"]),
            source_item_id=str(payload["source_item_id"]),
            occurred_at=float(payload["occurred_at"]),
            captured_at=float(payload["captured_at"]),
            title=str(payload["title"]),
            summary=str(payload["summary"]),
            retention_mode=str(payload["retention_mode"]),
            raw_payload_ref=payload.get("raw_payload_ref"),
            content_blocks=[
                TimelineContentBlock(
                    kind=str(block.get("kind", "text")),
                    value=str(block.get("value", "")),
                    mime_type=block.get("mime_type"),
                )
                for block in payload.get("content_blocks", [])
            ],
            entities=list(payload.get("entities", [])),
            tags=list(payload.get("tags", [])),
            privacy_labels=list(payload.get("privacy_labels", [])),
            processing_status=dict(payload.get("processing_status", {})),
            provenance=dict(payload.get("provenance", {})),
        )
