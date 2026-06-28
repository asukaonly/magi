"""Small normalization helpers for the L2 cognition store."""

from __future__ import annotations

from typing import Iterable, SupportsFloat, SupportsInt, cast

from ..ontology import coerce_unknown_entity_type


_EVENT_ID_PREFIXES = ("event:", "event :", "#")


def normalize_event_ids(items: Iterable[object] | None) -> list[str]:
    """Strip ``event:``/``#`` decoration that LLMs sometimes copy from prompts."""
    if not items:
        return []
    out: list[str] = []
    for raw in items:
        s = str(raw).strip()
        lowered = s.lower()
        for prefix in _EVENT_ID_PREFIXES:
            if lowered.startswith(prefix):
                s = s[len(prefix):].strip()
                break
        if s:
            out.append(s)
    return out


MOMENTARY_TRAITS = {"annoyance", "irritation", "frustration"}
SNAPSHOT_HISTORY_LIMIT = 5
MOOD_TRAJECTORY_FAMILIES = {"mood", "stress", "engagement"}
MOOD_TRAJECTORY_LIMIT = 20
DEFAULT_FUTURE_INTENT_TTL_SECONDS = 30 * 24 * 3600
MAX_EVIDENCE_EVENT_IDS = 50
CONFIDENCE_ACCUMULATION_CAP = 0.99
SINGLE_EVENT_CONFIDENCE_CAP = 0.3


def _l2_setting(group: str, attr: str, default: object) -> object:
    """Read an ``agent.memory.l2.<group>.<attr>`` value, falling back to *default*.

    Pure L2 helpers run in contexts without a bound config (isolated unit and
    benchmark stores), so any failure to resolve the config returns the supplied
    default rather than raising. The config loader caches by file signature, so
    repeated calls are cheap.
    """
    try:
        from ....config import get_config

        node = getattr(get_config().agent.memory.l2, group)
        return getattr(node, attr)
    except Exception:
        return default


def _coerce_l2_int(value: object) -> int:
    if isinstance(value, (str, bytes, bytearray, SupportsInt)):
        return int(value)
    raise TypeError(f"Expected an int-compatible L2 setting, got {type(value).__name__}")


def _coerce_l2_float(value: object) -> float:
    if isinstance(value, (str, bytes, bytearray, SupportsFloat)):
        return float(value)
    raise TypeError(f"Expected a float-compatible L2 setting, got {type(value).__name__}")


def _l2_limit(attr: str, default: int) -> int:
    return _coerce_l2_int(_l2_setting("limits", attr, default))


def snapshot_history_limit() -> int:
    """Max retained entries per ToM snapshot history field."""
    return _l2_limit("snapshot_history_limit", SNAPSHOT_HISTORY_LIMIT)


def mood_trajectory_limit() -> int:
    """Max retained entries in a ToM snapshot mood/stress/engagement trajectory."""
    return _l2_limit("mood_trajectory_limit", MOOD_TRAJECTORY_LIMIT)


def max_evidence_event_ids() -> int:
    """Max evidence event IDs retained per edge/assertion/facet merge."""
    return _l2_limit("max_evidence_event_ids", MAX_EVIDENCE_EVENT_IDS)


def confidence_accumulation_cap() -> float:
    """Noisy-OR confidence ceiling for accumulated edge/facet evidence."""
    return _coerce_l2_float(_l2_setting("confidence", "accumulation_cap", CONFIDENCE_ACCUMULATION_CAP))


def single_event_confidence_cap() -> float:
    """Confidence ceiling for claims/assertions from a single-event extraction batch."""
    return _coerce_l2_float(_l2_setting("confidence", "single_event_cap", SINGLE_EVENT_CONFIDENCE_CAP))




def normalize_store_entity_type(entity_type: str | None) -> str | None:
    if entity_type is None:
        return None
    text = str(entity_type).strip().lower()
    if not text:
        return None
    if text in {"user", "assistant", "system"}:
        return text
    return cast(str, coerce_unknown_entity_type(text))


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
    """Combine old and new confidence using noisy-OR, clamped to the configured cap."""
    combined = 1.0 - (1.0 - max(0.0, old)) * (1.0 - max(0.0, new))
    return min(combined, confidence_accumulation_cap())
