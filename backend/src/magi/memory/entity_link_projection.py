"""Canonical representation for L2-owned L1 entity-link projections."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence

DesiredEntityLink = tuple[str, str | None, float | None]


def normalize_desired_entity_links(
    links: Sequence[DesiredEntityLink],
) -> tuple[DesiredEntityLink, ...]:
    """Validate, deduplicate, and sort one desired entity-link set."""

    normalized: dict[str, tuple[str | None, float | None]] = {}
    for entity_id, entity_type, confidence in links:
        normalized_entity_id = str(entity_id or "").strip()
        if not normalized_entity_id:
            raise ValueError("entity_id must not be empty")
        normalized_confidence: float | None = None
        if confidence is not None:
            normalized_confidence = float(confidence)
            if not math.isfinite(normalized_confidence):
                raise ValueError("entity-link confidence must be finite")
            if not 0.0 <= normalized_confidence <= 1.0:
                raise ValueError("entity-link confidence must be between 0 and 1")
        normalized[normalized_entity_id] = (
            str(entity_type).strip() if entity_type is not None else None,
            normalized_confidence,
        )
    return tuple(
        (entity_id, entity_type, confidence)
        for entity_id, (entity_type, confidence) in sorted(normalized.items())
    )


def desired_entity_links_json(links: Sequence[DesiredEntityLink]) -> str:
    """Return the canonical JSON material shared by the L2 outbox and L1."""

    normalized = normalize_desired_entity_links(links)
    return json.dumps(
        [
            {
                "confidence": confidence,
                "entity_id": entity_id,
                "entity_type": entity_type,
            }
            for entity_id, entity_type, confidence in normalized
        ],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def desired_entity_links_fingerprint(links: Sequence[DesiredEntityLink]) -> str:
    """Return a stable fingerprint of the canonical desired-link payload."""

    material = desired_entity_links_json(links)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def desired_entity_links_from_json(payload_json: str) -> tuple[DesiredEntityLink, ...]:
    """Decode and validate canonical entity-link JSON from durable storage."""

    payload = json.loads(payload_json)
    if not isinstance(payload, list):
        raise RuntimeError("Invalid event entity-link projection payload")
    links: list[DesiredEntityLink] = []
    for item in payload:
        if not isinstance(item, dict):
            raise RuntimeError("Invalid event entity-link projection item")
        entity_id = item.get("entity_id")
        if not isinstance(entity_id, str) or not entity_id.strip():
            raise RuntimeError("Invalid event entity-link projection entity ID")
        entity_type = item.get("entity_type")
        confidence = item.get("confidence")
        if entity_type is not None and not isinstance(entity_type, str):
            raise RuntimeError("Invalid event entity-link projection entity type")
        if confidence is not None and not isinstance(confidence, (int, float)):
            raise RuntimeError("Invalid event entity-link projection confidence")
        links.append((entity_id, entity_type, confidence))
    try:
        return normalize_desired_entity_links(links)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Invalid event entity-link projection payload") from exc


__all__ = [
    "DesiredEntityLink",
    "desired_entity_links_fingerprint",
    "desired_entity_links_from_json",
    "desired_entity_links_json",
    "normalize_desired_entity_links",
]
