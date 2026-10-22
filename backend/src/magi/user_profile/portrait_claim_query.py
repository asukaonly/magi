"""Read-only Claim query for tentative self-report portrait lines."""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .portrait_signal_policy import (
    classify_tentative_portrait_claim,
    tentative_portrait_prompt_line,
)


@dataclass(frozen=True, slots=True)
class TentativePortraitClaim:
    """One visible, deterministic self-report candidate for the portrait prompt."""

    claim_id: str
    slot_key: str
    value_fingerprint: str
    prompt_line: str
    basis_refs: tuple[str, ...]
    changed_at: float


async def list_tentative_portrait_claims(
    l2_store: Any,
    *,
    user_id: str,
    current_assertion_ids: Iterable[str] = (),
    visible_assertion_ids: Iterable[str] = (),
    limit: int = 100,
    effective_at: float | None = None,
) -> list[TentativePortraitClaim]:
    """Return current self-reports that have no durable portrait assertion."""

    if l2_store is None:
        return []
    at = float(effective_at if effective_at is not None else time.time())
    bounded_limit = max(1, min(int(limit), 500))
    inputs = await l2_store.self_reports.load(
        user_id=user_id, current_assertion_ids=current_assertion_ids,
        visible_assertion_ids=visible_assertion_ids, effective_at=at,
    )
    current_route_value_keys = inputs.current_route_value_keys
    visible_route_value_keys = inputs.visible_route_value_keys
    provisional: list[TentativePortraitClaim] = []

    for candidate_input in inputs.candidates:
        claim_id = candidate_input.claim_id
        decision = classify_tentative_portrait_claim(
            candidate_input.claim,
            candidate_input.route_outcome,
        )
        if decision is None:
            continue
        basis_event_ids = candidate_input.event_ids[:3]
        if not basis_event_ids:
            continue
        prompt_line = tentative_portrait_prompt_line(decision.statement)
        if not prompt_line:
            continue
        provisional.append(
            TentativePortraitClaim(
                claim_id=claim_id,
                slot_key=decision.slot_key,
                value_fingerprint=decision.value_fingerprint,
                prompt_line=prompt_line,
                basis_refs=tuple(f"event:{event_id}" for event_id in basis_event_ids),
                changed_at=max(
                    _float(candidate_input.claim.get("updated_at")),
                    _float(candidate_input.route_outcome.get("created_at")),
                ),
            )
        )

    values_by_slot: dict[str, set[str]] = {}
    for slot_key, value_fingerprint in current_route_value_keys.union(visible_route_value_keys):
        values_by_slot.setdefault(slot_key, set()).add(value_fingerprint)
    for candidate in provisional:
        values_by_slot.setdefault(candidate.slot_key, set()).add(candidate.value_fingerprint)
    conflicted_slots = {
        slot_key
        for slot_key, value_fingerprints in values_by_slot.items()
        if len(value_fingerprints) > 1
    }

    candidates: list[TentativePortraitClaim] = []
    # A current Assertion that is still in review is not visible in either the
    # portrait world or recent context. Keep its source Claim eligible for the
    # explicitly tentative prompt path, while still using every current value
    # above to quarantine genuinely conflicted slots.
    seen_route_values = set(visible_route_value_keys)
    for candidate in provisional:
        route_value_key = (candidate.slot_key, candidate.value_fingerprint)
        if candidate.slot_key in conflicted_slots or route_value_key in seen_route_values:
            continue
        seen_route_values.add(route_value_key)
        candidates.append(candidate)
        if len(candidates) >= bounded_limit:
            break
    return candidates


async def latest_portrait_claim_change_at(l2_store: Any, *, user_id: str) -> float:
    """Return the memory owner's current self-report change watermark."""
    if l2_store is None:
        return 0.0
    return await l2_store.self_reports.latest_change_at(user_id=user_id)


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


__all__ = [
    "TentativePortraitClaim",
    "latest_portrait_claim_change_at",
    "list_tentative_portrait_claims",
]
