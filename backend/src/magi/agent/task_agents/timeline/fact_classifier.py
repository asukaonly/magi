"""Fact classification helpers for timeline task agents."""
from __future__ import annotations

from typing import Iterable

from ....agent.runtime.contracts import FactRecord
from .contracts import TimelinePayload


class TimelineFactClassifier:
    """Extracts normalized timeline payloads from runtime facts."""

    def classify(self, latest_fact: FactRecord | None, batch_facts: Iterable[FactRecord]) -> TimelinePayload:
        source_type = "unknown"
        source_item_id = None
        content: dict[str, object] = {}

        for fact in batch_facts:
            payload = fact.payload if isinstance(fact.payload, dict) else {}
            if payload.get("source_type"):
                source_type = str(payload["source_type"])
            if payload.get("source_item_id"):
                source_item_id = str(payload["source_item_id"])
            if payload:
                content.update(payload)

        if latest_fact is not None and isinstance(latest_fact.payload, dict):
            source_type = str(latest_fact.payload.get("source_type", source_type))
            source_item_id = str(latest_fact.payload.get("source_item_id", source_item_id or "")) or source_item_id
            content.update(latest_fact.payload)

        return TimelinePayload(
            source_type=source_type,
            source_item_id=source_item_id,
            content=content,
        )
