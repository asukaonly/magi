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


@pytest.mark.parametrize(
    "case_expected_layer,case_trust,case_interaction_count",
    [
        pytest.param("crack", 0.6, 50, id="mid_trust_selects_crack"),
        pytest.param("crack", 0.8, 80, id="high_trust_without_milestone_stays_at_crack"),
        pytest.param("surface", 0.6, 5, id="interaction_count_breach_regresses"),
    ],
)
def test_breach_selection_requires_trust_and_interaction_thresholds(
    case_expected_layer, case_trust, case_interaction_count
) -> None:
    plan = _plan(config=_layered_config(), trust=case_trust, interactions=case_interaction_count)
    assert plan.active_layer == case_expected_layer


@pytest.mark.parametrize(
    "case_expected_layer,case_trust",
    [
        pytest.param("crack", 0.5, id="trust_drop_regresses_from_revealed_to_crack"),
        pytest.param("surface", 0.2, id="trust_drop_regresses_all_the_way_to_surface"),
    ],
)
def test_trust_loss_regresses_to_the_supported_layer(case_expected_layer, case_trust) -> None:
    config = _layered_config()
    high = _plan(config=config, trust=0.8, interactions=80, milestone_keys=["guard_down"])
    breached = _plan(
        config=config, trust=case_trust, interactions=80, milestone_keys=["guard_down"]
    )
    assert high.active_layer == "revealed"
    assert breached.active_layer == case_expected_layer


@pytest.mark.parametrize("order", [(0, 1, 2), (2, 1, 0), (1, 2, 0)])
def test_layer_selection_ignores_declaration_order(order):
    config = _layered_config()
    layers = list(config.persona_layers)
    config.persona_layers = [layers[index] for index in order]
    plan = _plan(config=config, trust=0.8, interactions=80, milestone_keys=["guard_down"])
    assert plan.active_layer == "revealed"
    assert plan.layer_modifiers == {"k": "v_revealed"}


@pytest.mark.parametrize("has_surface", [False, True])
def test_layer_selection_respects_available_configuration(has_surface):
    config = PersonalityConfig(
        name="minimal",
        registers={"chat": Register(description="chat", behavior="b")},
        persona_layers=(
            [PersonaLayer(layer_id="surface", unlock_condition=None, modifiers={"k": "v"})]
            if has_surface
            else []
        ),
    )
    plan = _plan(config=config, trust=0.99, interactions=999)
    assert plan.active_layer == ("surface" if has_surface else None)
    assert plan.layer_modifiers == ({"k": "v"} if has_surface else {})
