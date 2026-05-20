"""Coverage for the 5 dynamic_state_rules keys planner exposes.

Three legacy keys (low_energy / high_stress / positive_mood) and two new
focus-driven keys (flow_state / distracted_state) added when we wrote
proper persona rules. Each rule fires when emotional_state matches the
documented threshold and only when the persona has the corresponding key
in its config.
"""

from __future__ import annotations

from magi.personality.loader import PersonalityConfig, Register
from magi.personality.models import EmotionalState
from magi.personality.turn_planner import PersonaTurnPlanner


def _config(rules: dict[str, str]) -> PersonalityConfig:
    return PersonalityConfig(
        name="t",
        registers={"chat": Register(description="chat", behavior="b")},
        dynamic_state_rules=rules,
    )


def _plan(*, config: PersonalityConfig, state: EmotionalState):
    return PersonaTurnPlanner().build_plan(
        config=config,
        user_message="hi",
        scenario="chat",
        task_category="chat",
        emotional_state=state,
    )


def test_low_energy_fires_below_threshold() -> None:
    plan = _plan(
        config=_config({"low_energy": "tired text"}),
        state=EmotionalState(energy_level=0.30),
    )
    assert plan.dynamic_modulations == {"active_rules": {"low_energy": "tired text"}}


def test_low_energy_silent_above_threshold() -> None:
    plan = _plan(
        config=_config({"low_energy": "tired text"}),
        state=EmotionalState(energy_level=0.50),
    )
    assert plan.dynamic_modulations == {}


def test_high_stress_fires_above_threshold() -> None:
    plan = _plan(
        config=_config({"high_stress": "stressed text"}),
        state=EmotionalState(stress_level=0.80),
    )
    assert plan.dynamic_modulations == {"active_rules": {"high_stress": "stressed text"}}


def test_positive_mood_fires_for_recognized_moods() -> None:
    for mood in ("happy", "excited", "positive", "good"):
        plan = _plan(
            config=_config({"positive_mood": "warm text"}),
            state=EmotionalState(current_mood=mood),
        )
        assert plan.dynamic_modulations == {"active_rules": {"positive_mood": "warm text"}}, mood


def test_flow_state_fires_when_focus_is_flow() -> None:
    plan = _plan(
        config=_config({"flow_state": "in the zone"}),
        state=EmotionalState(focus_state="flow"),
    )
    assert plan.dynamic_modulations == {"active_rules": {"flow_state": "in the zone"}}


def test_distracted_state_fires_when_focus_is_distracted() -> None:
    plan = _plan(
        config=_config({"distracted_state": "scattered"}),
        state=EmotionalState(focus_state="distracted"),
    )
    assert plan.dynamic_modulations == {"active_rules": {"distracted_state": "scattered"}}


def test_focus_state_normal_silences_focus_keys() -> None:
    plan = _plan(
        config=_config({"flow_state": "in the zone", "distracted_state": "scattered"}),
        state=EmotionalState(focus_state="normal"),
    )
    assert plan.dynamic_modulations == {}


def test_unknown_keys_in_config_are_ignored() -> None:
    """Persona authors who add an unrecognised key see it silently dropped —
    no exception, just no effect. The planner only consumes the 5
    well-known keys."""
    plan = _plan(
        config=_config({"made_up_key": "should not surface"}),
        state=EmotionalState(energy_level=0.10, stress_level=0.95),
    )
    assert plan.dynamic_modulations == {}


def test_distracted_and_high_stress_can_coexist() -> None:
    """focus_state="distracted" requires stress > 0.8 in the engine. That
    stricter threshold means whenever distracted_state fires, high_stress
    is also above its own 0.70 threshold, so both rules fire together.
    The planner emits both — they describe different facets of the same
    underlying load."""
    plan = _plan(
        config=_config({
            "high_stress": "stressed text",
            "distracted_state": "scattered",
        }),
        state=EmotionalState(stress_level=0.90, focus_state="distracted"),
    )
    active = plan.dynamic_modulations.get("active_rules", {})
    assert active.get("high_stress") == "stressed text"
    assert active.get("distracted_state") == "scattered"


def test_flow_and_positive_mood_can_coexist() -> None:
    """High-energy + low-stress (focus=flow) frequently coincides with a
    happy mood. Both rules fire — they describe orthogonal facets
    (cognitive engagement vs emotional valence)."""
    plan = _plan(
        config=_config({
            "positive_mood": "warm text",
            "flow_state": "in the zone",
        }),
        state=EmotionalState(
            current_mood="happy",
            focus_state="flow",
        ),
    )
    active = plan.dynamic_modulations.get("active_rules", {})
    assert active.get("positive_mood") == "warm text"
    assert active.get("flow_state") == "in the zone"
