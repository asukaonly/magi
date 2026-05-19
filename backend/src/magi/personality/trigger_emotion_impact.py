"""Trigger-driven emotional state updates.

When a signature trigger fires during a turn, the planner records it on
``EmotionalState.recent_active_trigger_ids``. Post-process then resolves
each fired trigger's emotional impact (mood/stress/energy delta) and
applies it on top of the outcome-based deltas computed by
``EmotionalStateEngine._calculate_*_change``.

Without this layer, every persona would react identically to the same
``InteractionOutcome`` regardless of which trigger fired — i.e., Seven's
``absurdity`` firing on a joke would move her mood by the same amount as
Echo's ``protocol_question`` firing on a procedural inquiry. By coupling
mood updates to per-persona signature triggers (which P1 already made
config-driven), we get persona-differentiated emotional reactivity for
free: the persona's existing trigger list IS the persona's reactivity
profile.

Resolution order:
1. Explicit ``emotion_impact`` on the SignatureTrigger wins outright.
2. Otherwise, a family default keyed on ``trigger_id.lower()`` applies.
3. Otherwise, no impact — the planner still uses the trigger for
   behavior_shift, but mood/stress/energy stay where the outcome math
   left them.

Family defaults are intentionally short — they cover the recurring
archetype names from the architecture doc (``crisis``, ``absurdity``,
``hostility``, etc.). New trigger IDs the LLM router invents will simply
default to zero impact unless the persona author opts in explicitly.
"""

from __future__ import annotations

from .loader import SignatureTrigger


_IMPACT_KEYS = ("mood", "stress", "energy")


# Family defaults keyed on lowercase trigger_id. Authors can override any
# value per-trigger via ``signature_triggers[*].emotion_impact``.
DEFAULT_TRIGGER_EMOTION_IMPACTS: dict[str, dict[str, float]] = {
    # Crisis-class: emotional load up, energy drains a little.
    "crisis": {"stress": 0.20, "energy": -0.05},
    "safety": {"stress": 0.20, "energy": -0.05},
    # Hostility / boundary push: stress up, slight mood drop.
    "hostility": {"mood": -0.05, "stress": 0.15},
    "boundary_violation": {"mood": -0.05, "stress": 0.15},
    # Play / absurdity: mood up, small energy lift.
    "absurdity": {"mood": 0.10, "energy": 0.03},
    "play": {"mood": 0.10, "energy": 0.03},
    # Domain / interest zone: energy lift, slight mood up.
    "domain_hotzone": {"mood": 0.05, "energy": 0.10},
    "technical_interest": {"mood": 0.05, "energy": 0.10},
    "interest_zone": {"mood": 0.05, "energy": 0.10},
    # Emotional resonance: mutual care lowers tension.
    "emotional_resonance": {"stress": -0.10},
    "emotional": {"stress": -0.10},
    # Intimacy / trust: mood up, stress down.
    "intimacy": {"mood": 0.08, "stress": -0.05},
    # Value topic / judgment: small engaged-thought mood lift.
    "value_topic": {"mood": 0.03},
    "judgment": {"mood": 0.03},
}


def resolve_trigger_emotion_impact(trigger: SignatureTrigger) -> dict[str, float]:
    """Return the mood/stress/energy delta for ``trigger`` activating once.

    Explicit ``emotion_impact`` on the trigger wins over family defaults.
    Returns an empty dict when neither is available — caller should treat
    that as "this trigger has no effect on emotional state".
    """
    if trigger.emotion_impact:
        return {
            key: float(value)
            for key, value in trigger.emotion_impact.items()
            if key in _IMPACT_KEYS
        }
    family_default = DEFAULT_TRIGGER_EMOTION_IMPACTS.get(
        str(trigger.trigger_id or "").strip().lower(),
        {},
    )
    return dict(family_default)


def resolve_emotion_impacts_for_ids(
    trigger_ids: list[str],
    signature_triggers: list[SignatureTrigger],
) -> list[dict[str, float]]:
    """Look up each ``trigger_id`` in ``signature_triggers`` and resolve impact.

    Unknown IDs (LLM hallucinations, removed triggers) are silently
    skipped. Triggers that resolve to an empty impact are also skipped so
    the caller does not waste cycles applying no-op deltas.
    """
    by_id = {
        str(trigger.trigger_id or "").strip(): trigger
        for trigger in signature_triggers
        if str(trigger.trigger_id or "").strip()
    }
    impacts: list[dict[str, float]] = []
    for raw_id in trigger_ids:
        trigger_id = str(raw_id or "").strip()
        if not trigger_id:
            continue
        trigger = by_id.get(trigger_id)
        if trigger is None:
            continue
        impact = resolve_trigger_emotion_impact(trigger)
        if impact:
            impacts.append(impact)
    return impacts


__all__ = [
    "DEFAULT_TRIGGER_EMOTION_IMPACTS",
    "resolve_emotion_impacts_for_ids",
    "resolve_trigger_emotion_impact",
]
