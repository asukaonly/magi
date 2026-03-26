"""Domain-neutral sensor output contracts (L9 - Awareness layer)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class ContentBlock:
    """A typed content fragment within a sensor output."""

    kind: str  # "text" | "image" | "audio" | "metric" | "structured"
    value: str  # Content or reference (path, URL)
    mime_type: str | None = None


@dataclass(slots=True, frozen=True)
class SensorMemoryPolicy:
    """Declarative memory routing policy for a sensor's outputs.

    Each sensor class declares a static memory policy. The ingestion gateway
    reads this policy to set the correct MemoryEvent fields without the sensor
    needing to understand L0-L4 internals.
    """

    memory_domain: str = "external_activity"
    ingest_target: str = "l1_only"
    cognition_eligible: bool = True
    tom_depth: str = "none"
    retention_class: str = "compressible"
    importance_bias: float = 0.5
    author_type: str = "external"
    content_type: str = "observation"


@dataclass(slots=True)
class SensorOutput:
    """Domain-neutral output produced by all sensors."""

    # Identity
    source_type: str
    source_item_id: str

    # Temporal
    occurred_at: float
    captured_at: float

    # Content
    title: str
    summary: str
    content_blocks: list[ContentBlock] = field(default_factory=list)
    raw_payload_ref: str | None = None

    # Classification
    tags: list[str] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)

    # Provenance
    provenance: dict[str, Any] = field(default_factory=dict)

    # Sensor-specific structured data for downstream consumers
    domain_payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["content_blocks"] = [asdict(b) for b in self.content_blocks]
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SensorOutput:
        blocks = [
            ContentBlock(
                kind=str(b.get("kind", "text")),
                value=str(b.get("value", "")),
                mime_type=b.get("mime_type"),
            )
            for b in data.get("content_blocks", [])
        ]
        return cls(
            source_type=str(data["source_type"]),
            source_item_id=str(data["source_item_id"]),
            occurred_at=float(data["occurred_at"]),
            captured_at=float(data["captured_at"]),
            title=str(data.get("title", "")),
            summary=str(data.get("summary", "")),
            content_blocks=blocks,
            raw_payload_ref=data.get("raw_payload_ref"),
            tags=list(data.get("tags", [])),
            entities=list(data.get("entities", [])),
            provenance=dict(data.get("provenance", {})),
            domain_payload=dict(data.get("domain_payload", {})),
        )


@dataclass(slots=True)
class SensorOutputMetadata:
    """Extracted metadata for a sensor output item."""

    entities: list[dict[str, Any]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    relation_candidates: list[dict[str, Any]] = field(default_factory=list)
