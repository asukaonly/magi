"""Layer selection regresses cleanly when relationship state degrades.

P3.2: ``_select_layer`` used to iterate layers in JSON declaration order
and keep the last match. That made the result order-dependent (an
AI-generated config emitting ``[revealed, crack, surface]`` would always
pick ``surface`` regardless of trust) and meant the breach scenario
(``trust`` decays below revealed's threshold) silently kept the layer
at revealed if the loop happened to land there last.

The fixed implementation re-evaluates each turn and picks the strictest
currently-matching layer, independent of JSON order.
"""

from __future__ import annotations

import pytest

from magi.personality.loader import PersonaLayer, PersonalityConfig, Register
from magi.personality.turn_planner import PersonaTurnPlanner


def _layered_config(layer_order: list[PersonaLayer] | None = None) -> PersonalityConfig:
    surface = PersonaLayer(layer_id="surface", unlock_condition=None, modifiers={"k": "v_surface"})
    crack = PersonaLayer(
        layer_id="crack",
        unlock_condition={"trust_level_gte": 0.45, "interaction_count_gte": 30},
        modifiers={"k": "v_crack"},
    )
    revealed = PersonaLayer(
        layer_id="revealed",
        unlock_condition={"trust_level_gte": 0.75, "milestone_required": "guard_down"},
        modifiers={"k": "v_revealed"},
    )
    return PersonalityConfig(
        name="layered",
        registers={"chat": Register(description="chat", behavior="b")},
        persona_layers=layer_order or [surface, crack, revealed],
    )


def _plan(
    *,
    config: PersonalityConfig,
    trust: float,
    interactions: int = 0,
    milestone_keys: list[str] | None = None,
):
    return PersonaTurnPlanner().build_plan(
        config=config,
        user_message="hi",
        scenario="chat",
        task_category="chat",
        relationship={"trust_level": trust, "total_interactions": interactions},
        milestones=[{"key": key} for key in (milestone_keys or [])],
    )


def test_low_trust_selects_surface() -> None:
    plan = _plan(config=_layered_config(), trust=0.2)
    assert plan.active_layer == "surface"
    assert plan.layer_modifiers == {"k": "v_surface"}


def test_mid_trust_selects_crack() -> None:
    plan = _plan(config=_layered_config(), trust=0.6, interactions=50)
    assert plan.active_layer == "crack"


def test_high_trust_with_milestone_selects_revealed() -> None:
    plan = _plan(
        config=_layered_config(),
        trust=0.8,
        interactions=80,
        milestone_keys=["guard_down"],
    )
    assert plan.active_layer == "revealed"


def test_high_trust_without_milestone_stays_at_crack() -> None:
    """Trust passes but milestone gate not met → revealed is locked, crack wins."""
    plan = _plan(config=_layered_config(), trust=0.8, interactions=80)
    assert plan.active_layer == "crack"


def test_trust_drop_regresses_from_revealed_to_crack() -> None:
    config = _layered_config()
    high = _plan(config=config, trust=0.8, interactions=80, milestone_keys=["guard_down"])
    breached = _plan(config=config, trust=0.5, interactions=80, milestone_keys=["guard_down"])
    assert high.active_layer == "revealed"
    assert breached.active_layer == "crack"


def test_trust_drop_regresses_all_the_way_to_surface() -> None:
    config = _layered_config()
    high = _plan(config=config, trust=0.8, interactions=80, milestone_keys=["guard_down"])
    broken = _plan(config=config, trust=0.2, interactions=80, milestone_keys=["guard_down"])
    assert high.active_layer == "revealed"
    assert broken.active_layer == "surface"


def test_reverse_json_order_still_picks_strictest_match() -> None:
    """Regression for the original bug: JSON-order dependency."""
    config = _layered_config()
    layers = list(config.persona_layers)
    config_reversed = PersonalityConfig(
        name="layered_reversed",
        registers={"chat": Register(description="chat", behavior="b")},
        persona_layers=list(reversed(layers)),
    )
    plan = _plan(
        config=config_reversed,
        trust=0.8,
        interactions=80,
        milestone_keys=["guard_down"],
    )
    assert plan.active_layer == "revealed"


def test_jumbled_json_order_still_picks_strictest_match() -> None:
    config = _layered_config()
    crack, surface, revealed = (
        config.persona_layers[1],
        config.persona_layers[0],
        config.persona_layers[2],
    )
    jumbled = PersonalityConfig(
        name="layered_jumbled",
        registers={"chat": Register(description="chat", behavior="b")},
        persona_layers=[crack, revealed, surface],
    )
    plan = _plan(
        config=jumbled,
        trust=0.8,
        interactions=80,
        milestone_keys=["guard_down"],
    )
    assert plan.active_layer == "revealed"


def test_only_surface_layer_returns_surface() -> None:
    surface_only = PersonalityConfig(
        name="surface_only",
        registers={"chat": Register(description="chat", behavior="b")},
        persona_layers=[
            PersonaLayer(layer_id="surface", unlock_condition=None, modifiers={"k": "v"}),
        ],
    )
    plan = _plan(config=surface_only, trust=0.99, interactions=999)
    assert plan.active_layer == "surface"


def test_no_persona_layers_returns_none() -> None:
    config = PersonalityConfig(
        name="layerless",
        registers={"chat": Register(description="chat", behavior="b")},
        persona_layers=[],
    )
    plan = _plan(config=config, trust=0.99)
    assert plan.active_layer is None
    assert plan.layer_modifiers == {}


def test_interaction_count_breach_regresses() -> None:
    """If crack requires 30 interactions and the count dips below (e.g. an
    out-of-band reset cleared the counter), the planner should fall back to
    surface even if trust is high enough on paper."""
    plan = _plan(config=_layered_config(), trust=0.6, interactions=5)
    assert plan.active_layer == "surface"
