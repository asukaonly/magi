"""Small normalization helpers for the L2 cognition store."""

from __future__ import annotations

from ..ontology import coerce_unknown_entity_type


STRESS_KEYWORDS = ("stress", "stressed", "anxious", "anxiety", "pressure")
CALM_KEYWORDS = ("calm", "relaxed", "relief", "peaceful")
MOMENTARY_TRAITS = {"annoyance", "irritation", "frustration"}
SNAPSHOT_HISTORY_LIMIT = 5
MOOD_TRAJECTORY_FAMILIES = {"mood", "stress", "engagement"}
MOOD_TRAJECTORY_LIMIT = 20
DEFAULT_FUTURE_INTENT_TTL_SECONDS = 30 * 24 * 3600
MAX_EVIDENCE_EVENT_IDS = 50


def normalize_store_entity_type(entity_type: str | None) -> str | None:
    if entity_type is None:
        return None
    text = str(entity_type).strip().lower()
    if not text:
        return None
    if text in {"user", "assistant", "system"}:
        return text
    return coerce_unknown_entity_type(text)


def normalize_store_entity_ref(entity_id: str | None, entity_type: str | None) -> str | None:
    if entity_id is None:
        return None
    text = str(entity_id).strip()
    if not text or not entity_type or ":" not in text:
        return text or None
    _, _, suffix = text.partition(":")
    if not suffix:
        return text
    return f"{entity_type}:{suffix}"


def accumulate_confidence(old: float, new: float) -> float:
    """Combine old and new confidence using noisy-OR, clamped to [0.0, 0.99]."""
    combined = 1.0 - (1.0 - max(0.0, old)) * (1.0 - max(0.0, new))
    return min(combined, 0.99)
