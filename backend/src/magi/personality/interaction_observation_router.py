"""Route post-turn observer memory candidates into owned stores."""

from __future__ import annotations

import time
from typing import Any, Iterable

from ..core.logger import get_logger
from .interaction_analyzer import InteractionObservation

logger = get_logger(__name__)

_PROFILE_FAMILIES = {
    "identity_profile",
    "communication_profile",
    "preference_profile",
    "routine_profile",
    "state_profile",
}


async def apply_interaction_observations(
    *,
    observations: Iterable[InteractionObservation],
    user_id: str,
    user_message: str,
    unified_memory: Any,
    self_memory: Any,
    persona_id: str | None = None,
    session_id: str | None = None,
    turn_id: str | None = None,
) -> bool:
    """Apply validated observer candidates to the stores that own them."""
    normalized_user_id = str(user_id or "").strip()
    if not normalized_user_id:
        return False

    updated = False
    for observation in list(observations or [])[:3]:
        try:
            if observation.kind == "profile_signal":
                updated = (
                    await _apply_profile_signal(
                        observation=observation,
                        user_id=normalized_user_id,
                        user_message=user_message,
                        unified_memory=unified_memory,
                        turn_id=turn_id,
                    )
                    or updated
                )
            elif observation.kind == "task_preference":
                updated = (
                    await _apply_task_preference(
                        observation=observation,
                        unified_memory=unified_memory,
                        user_message=user_message,
                        user_id=normalized_user_id,
                        persona_id=persona_id,
                        session_id=session_id,
                        turn_id=turn_id,
                    )
                    or updated
                )
            elif observation.kind == "persona_relationship_signal":
                updated = (
                    await _apply_persona_relationship_signal(
                        observation=observation,
                        self_memory=self_memory,
                        user_message=user_message,
                        user_id=normalized_user_id,
                        persona_id=persona_id,
                        session_id=session_id,
                        turn_id=turn_id,
                    )
                    or updated
                )
        except Exception as exc:  # pragma: no cover - defensive isolation
            logger.warning(
                "Failed to apply interaction observation",
                kind=getattr(observation, "kind", ""),
                error=str(exc),
            )
    return updated


async def _apply_profile_signal(
    *,
    observation: InteractionObservation,
    user_id: str,
    user_message: str,
    unified_memory: Any,
    turn_id: str | None,
) -> bool:
    l2 = getattr(unified_memory, "l2", None) if unified_memory is not None else None
    if l2 is None or not hasattr(l2, "upsert_assertion_candidate"):
        return False

    args = observation.arguments or {}
    trait_family = _text(args.get("trait_family")).casefold()
    trait_name = _text(args.get("trait_name"))
    trait_value = _text(args.get("trait_value"))
    evidence_text = _text(args.get("evidence_text"))
    confidence = _clamp_float(args.get("confidence"), default=0.0)

    if trait_family not in _PROFILE_FAMILIES:
        return False
    if not trait_name or not trait_value or not evidence_text:
        return False
    if confidence < 0.65:
        return False
    if not _is_grounded_in_user_message(evidence_text, user_message):
        return False

    now = time.time()
    evidence_id = _text(turn_id)
    candidate = {
        "entity_id": f"user:{user_id}",
        "entity_type": "user",
        "trait_family": trait_family,
        "trait_name": trait_name,
        "trait_value": trait_value,
        "confidence_score": confidence,
        "evidence_events": [evidence_id] if evidence_id else [],
        "volatility_index": 0.25 if trait_family != "state_profile" else 0.65,
        "source_domain": "conversation",
        "inference_depth": "explicit",
        "validation_state": "tentative",
        "first_inferred_at": now,
        "last_validated_at": now,
        "target_entity_id": "",
        "target_entity_type": "",
        "target_scope": "global",
        "temporal_scope": "momentary" if trait_family == "state_profile" else "stable",
        "decay_policy": None,
        "decay_anchor_at": now,
        "context_ref_id": evidence_id,
        "expires_at": None,
        "memory_subdomain": "state" if trait_family == "state_profile" else "semantic",
        "natural_summary": evidence_text[:500],
    }
    await l2.upsert_assertion_candidate(candidate)
    return True


async def _apply_task_preference(
    *,
    observation: InteractionObservation,
    unified_memory: Any,
    user_message: str,
    user_id: str,
    persona_id: str | None,
    session_id: str | None,
    turn_id: str | None,
) -> bool:
    l4 = getattr(unified_memory, "l4", None) if unified_memory is not None else None
    if l4 is None or not hasattr(l4, "record_task_preference"):
        return False
    args = observation.arguments or {}
    preference = _text(args.get("preference"))
    confidence = _clamp_float(args.get("confidence"), default=0.0)
    if not preference or confidence < 0.65:
        return False
    evidence_text = _text(args.get("evidence_text"))
    if not _is_grounded_in_user_message(evidence_text, user_message):
        return False
    return bool(
        await l4.record_task_preference(
            user_id=user_id,
            persona_id=_text(persona_id),
            task_category=_text(args.get("task_category")) or "chat",
            preference=preference,
            polarity=_text(args.get("polarity")) or "prefer",
            evidence_text=evidence_text,
            confidence=confidence,
            turn_id=_text(turn_id),
            session_id=_text(session_id),
        )
    )


async def _apply_persona_relationship_signal(
    *,
    observation: InteractionObservation,
    self_memory: Any,
    user_message: str,
    user_id: str,
    persona_id: str | None,
    session_id: str | None,
    turn_id: str | None,
) -> bool:
    if self_memory is None or not hasattr(self_memory, "record_observer_relationship_signal"):
        return False
    args = observation.arguments or {}
    confidence = _clamp_float(args.get("confidence"), default=0.0)
    if confidence < 0.65:
        return False
    evidence_text = _text(args.get("evidence_text"))
    if not _is_grounded_in_user_message(evidence_text, user_message):
        return False
    return bool(
        await self_memory.record_observer_relationship_signal(
            user_id=user_id,
            persona_id=_text(persona_id),
            signal_type=_text(args.get("signal_type")) or "boundary",
            milestone_key=_text(args.get("milestone_key")),
            trust_delta=_clamp_float(args.get("trust_delta"), default=0.0, low=-0.2, high=0.2),
            evidence_text=evidence_text,
            confidence=confidence,
            turn_id=_text(turn_id),
            session_id=_text(session_id),
        )
    )


def _is_grounded_in_user_message(evidence_text: str, user_message: str) -> bool:
    evidence = _compact_for_match(evidence_text)
    message = _compact_for_match(user_message)
    if not evidence or not message:
        return False
    return evidence in message or message in evidence


def _compact_for_match(value: str) -> str:
    return "".join(str(value or "").split()).casefold()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _clamp_float(
    value: Any,
    *,
    default: float,
    low: float = 0.0,
    high: float = 1.0,
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, parsed))
