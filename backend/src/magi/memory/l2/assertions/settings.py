"""Config-aware settings for L2 assertion state and decay policy."""

from __future__ import annotations

from ..storage.utils import _coerce_l2_float, _coerce_l2_int, _l2_setting

CONFIDENCE_BASE = 0.3
CONFIDENCE_SLOPE = 0.25
CONFIDENCE_CEILING = 0.95
STABLE_EVIDENCE_COUNT = 3
STABLE_TIME_SPAN_HOURS = 24.0
CORROBORATED_EVIDENCE_COUNT = 2
USER_REJECTED_CONFIDENCE = 0.10
USER_CONFIRMED_CONFIDENCE_FLOOR = 0.85
EXPIRED_CONFIDENCE_CEILING = 0.30
CONTRADICTED_CONFIDENCE_CEILING = 0.35
STABLE_CONFIDENCE_FLOOR = 0.82
TEMPORARY_CORROBORATED_CONFIDENCE_FLOOR = 0.50
CORROBORATED_CONFIDENCE_FLOOR = 0.58
TENTATIVE_CONFIDENCE_CEILING = 0.30
MOMENTARY_TTL_SECONDS = 2 * 60 * 60
MOOD_TTL_SECONDS = 12 * 60 * 60
STRESS_TTL_SECONDS = 24 * 60 * 60
ENGAGEMENT_TTL_SECONDS = 12 * 60 * 60
GROUP_SENTIMENT_TTL_SECONDS = 6 * 60 * 60

_FAMILY_TTL_SETTING: dict[str, tuple[str, float]] = {
    "mood": ("mood_ttl_seconds", MOOD_TTL_SECONDS),
    "stress": ("stress_ttl_seconds", STRESS_TTL_SECONDS),
    "engagement": ("engagement_ttl_seconds", ENGAGEMENT_TTL_SECONDS),
    "group_atmosphere": ("group_sentiment_ttl_seconds", GROUP_SENTIMENT_TTL_SECONDS),
    "public_sentiment": ("group_sentiment_ttl_seconds", GROUP_SENTIMENT_TTL_SECONDS),
    "relationship_shift": ("group_sentiment_ttl_seconds", GROUP_SENTIMENT_TTL_SECONDS),
}


def assertion_float_setting(attr: str, default: float) -> float:
    """Read a float value from ``agent.memory.l2.assertion``."""

    return _coerce_l2_float(_l2_setting("assertion", attr, default))


def assertion_int_setting(attr: str, default: int) -> int:
    """Read an int value from ``agent.memory.l2.assertion``."""

    return _coerce_l2_int(_l2_setting("assertion", attr, default))


def momentary_ttl_seconds() -> float:
    """Configured TTL for entity-scoped momentary assertions."""

    return assertion_float_setting("momentary_ttl_seconds", MOMENTARY_TTL_SECONDS)


def configured_family_ttl_seconds(
    trait_family: str,
    default_ttl_seconds: float | int | None,
) -> float | None:
    """Return the configured TTL for a trait family, falling back to policy default."""

    key = str(trait_family or "").strip().casefold()
    setting = _FAMILY_TTL_SETTING.get(key)
    if setting is not None:
        attr, default = setting
        return assertion_float_setting(attr, default)
    if default_ttl_seconds is None:
        return None
    return float(default_ttl_seconds)


__all__ = [
    "CONFIDENCE_BASE",
    "CONFIDENCE_CEILING",
    "CONFIDENCE_SLOPE",
    "CORROBORATED_CONFIDENCE_FLOOR",
    "CORROBORATED_EVIDENCE_COUNT",
    "CONTRADICTED_CONFIDENCE_CEILING",
    "ENGAGEMENT_TTL_SECONDS",
    "EXPIRED_CONFIDENCE_CEILING",
    "GROUP_SENTIMENT_TTL_SECONDS",
    "MOMENTARY_TTL_SECONDS",
    "MOOD_TTL_SECONDS",
    "STABLE_CONFIDENCE_FLOOR",
    "STABLE_EVIDENCE_COUNT",
    "STABLE_TIME_SPAN_HOURS",
    "STRESS_TTL_SECONDS",
    "TEMPORARY_CORROBORATED_CONFIDENCE_FLOOR",
    "TENTATIVE_CONFIDENCE_CEILING",
    "USER_CONFIRMED_CONFIDENCE_FLOOR",
    "USER_REJECTED_CONFIDENCE",
    "assertion_float_setting",
    "assertion_int_setting",
    "configured_family_ttl_seconds",
    "momentary_ttl_seconds",
]
