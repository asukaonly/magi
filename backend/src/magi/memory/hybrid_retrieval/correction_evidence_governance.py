"""One fail-closed policy for answer-facing L1 correction evidence."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Literal


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class L1CorrectionEvidenceDecision:
    """Governance decision for one batch of candidate L1 event identities."""

    blocked_event_ids: frozenset[str]
    missing_event_id_count: int
    status: Literal["applied", "failed_closed"]
    reason: str | None = None
    drop_all: bool = False


async def decide_l1_correction_evidence(
    l2_store: Any,
    event_ids: list[str],
) -> L1CorrectionEvidenceDecision:
    """Resolve active corrections or fail closed when governance is unavailable."""
    normalized = [str(event_id or "").strip() for event_id in event_ids]
    missing_count = sum(1 for event_id in normalized if not event_id)
    known_ids = list(dict.fromkeys(event_id for event_id in normalized if event_id))
    db_path = getattr(l2_store, "db_path", None)
    if l2_store is None or not isinstance(db_path, str) or not db_path.strip():
        return _drop_all_decision(
            known_ids,
            missing_count=missing_count,
            reason="l2_governance_unavailable",
        )
    lookup = getattr(l2_store, "active_correction_evidence_event_ids", None)
    if not callable(lookup):
        return _drop_all_decision(
            known_ids,
            missing_count=missing_count,
            reason="lookup_unavailable",
        )
    try:
        raw_blocked = await lookup(known_ids)
    except Exception:
        logger.warning("L1 correction evidence lookup failed", exc_info=True)
        return _drop_all_decision(
            known_ids,
            missing_count=missing_count,
            reason="lookup_failed",
        )
    if not isinstance(raw_blocked, (set, frozenset, list, tuple)):
        return _drop_all_decision(
            known_ids,
            missing_count=missing_count,
            reason="lookup_invalid_result",
        )
    candidates = set(known_ids)
    if any(
        not isinstance(event_id, str) or not event_id.strip() or event_id.strip() not in candidates
        for event_id in raw_blocked
    ):
        return _drop_all_decision(
            known_ids,
            missing_count=missing_count,
            reason="lookup_invalid_result",
        )
    blocked = frozenset(event_id.strip() for event_id in raw_blocked)
    return L1CorrectionEvidenceDecision(
        blocked_event_ids=blocked,
        missing_event_id_count=missing_count,
        status="failed_closed" if missing_count else "applied",
        reason="missing_event_id" if missing_count else None,
    )


def _drop_all_decision(
    known_ids: list[str],
    *,
    missing_count: int,
    reason: str,
) -> L1CorrectionEvidenceDecision:
    logger.warning(
        "L1 correction evidence governance failed closed",
        extra={
            "reason": reason,
            "known_event_count": len(known_ids),
            "missing_event_id_count": missing_count,
        },
    )
    return L1CorrectionEvidenceDecision(
        blocked_event_ids=frozenset(known_ids),
        missing_event_id_count=missing_count,
        status="failed_closed",
        reason=reason,
        drop_all=True,
    )


__all__ = ["L1CorrectionEvidenceDecision", "decide_l1_correction_evidence"]
