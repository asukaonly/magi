"""Fact-kind admission helpers for the L2 cognition store."""

from __future__ import annotations

from ....core.logger import get_logger

logger = get_logger(__name__)


class L2StoreFactKindMixin:
    """Validate graph fact_kind values against their extraction lineage."""

    _EXPLICIT_SOURCES: set[str] = {"rule", "structured_hint", "source_explicit"}
    _STRUCTURED_SOURCES: set[str] = {"structured_hint", "rule"}

    _FACT_KIND_RULES: dict[str, set[str]] = {
        "public_topology": _EXPLICIT_SOURCES | _STRUCTURED_SOURCES,
        "stable_preference": _EXPLICIT_SOURCES,
    }

    @classmethod
    def _validate_fact_kind(
        cls,
        fact_kind: str,
        extraction_method: str,
        confidence: float,
    ) -> str:
        """Validate fact_kind against extraction_method, downgrading on mismatch."""
        if not fact_kind:
            return ""

        if fact_kind == "public_topology":
            allowed = cls._FACT_KIND_RULES["public_topology"]
            if extraction_method not in allowed and not (
                extraction_method in cls._STRUCTURED_SOURCES and confidence >= 0.8
            ):
                logger.warning(
                    "fact_kind_downgraded",
                    original=fact_kind,
                    extraction_method=extraction_method,
                    confidence=confidence,
                    target="explicit_fact",
                )
                return "explicit_fact"

        elif fact_kind == "stable_preference":
            allowed = cls._FACT_KIND_RULES["stable_preference"]
            if extraction_method not in allowed:
                logger.warning(
                    "fact_kind_downgraded",
                    original=fact_kind,
                    extraction_method=extraction_method,
                    target="explicit_fact",
                )
                return "explicit_fact"

        return fact_kind
