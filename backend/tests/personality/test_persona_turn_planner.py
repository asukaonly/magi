from __future__ import annotations

import json
from pathlib import Path

from magi.personality.loader import PersonalityConfig
from magi.personality.models import EmotionalState
from magi.personality.turn_planner import PersonaTurnPlanner


def _load_seven_config() -> PersonalityConfig:
    preset_path = Path(__file__).resolve().parents[2] / "personalities" / "zh" / "seven_hacker.json"
    return PersonalityConfig.from_dict(json.loads(preset_path.read_text(encoding="utf-8")))


def _trigger_ids(plan) -> list[str]:
    return [trigger.trigger_id for trigger in plan.active_triggers]


def _make_config() -> PersonalityConfig:
    return PersonalityConfig.from_dict(
        {
            "name": "Seven",
            "identity_core": {
                "identity_statement": "Distrusts empty systems and inspects hidden assumptions.",
                "values_loved": ["clarity"],
                "values_rejected": ["empty ceremony"],
                "attention_biases": ["hidden assumptions"],
            },
            "idiolect": {
                "sentence_style": "Fast, direct, and sparse.",
            },
            "registers": {
                "chat": {"description": "casual", "behavior": "Talk naturally."},
                "analysis": {"description": "analysis", "behavior": "Structure the answer."},
                "task": {"description": "task", "behavior": "Solve first."},
                "emotional": {"description": "emotional", "behavior": "Be steadier and less sharp."},
                "crisis": {"description": "crisis", "behavior": "Give brief operational steps."},
            },
            "signature_triggers": [
                {
                    "trigger_id": "domain_hotzone",
                    "activates_when": "The user discusses architecture, code, systems, or models.",
                    "behavior_shift": "Increase technical judgment.",
                    "intensity_levels": {"mid": "Visible but controlled."},
                },
                {
                    "trigger_id": "absurdity",
                    "activates_when": "The user brings absurd jokes.",
                    "behavior_shift": "Allow more play.",
                },
            ],
            "persona_layers": [
                {"layer_id": "surface", "unlock_condition": None, "modifiers": {}},
                {
                    "layer_id": "crack",
                    "unlock_condition": {"trust_level_gte": 0.4, "interaction_count_gte": 3},
                    "modifiers": {"memory_behavior": "May reference prior context lightly."},
                },
            ],
            "dynamic_state_rules": {
                "low_energy": "Be shorter.",
                "high_stress": "Match urgency.",
                "positive_mood": "Allow a little more play.",
            },
        }
    )


def test_planner_uses_analysis_register_and_quiet_clamp_for_architecture_turn() -> None:
    plan = PersonaTurnPlanner().build_plan(
        config=_make_config(),
        user_message="我们继续看 persona runtime architecture 怎么切",
        scenario="analysis",
        task_category="chat",
    )

    assert plan.register == "analysis"
    assert plan.persona_intensity == 1
    assert plan.quiet_hours[0]["condition"] == "focused_work"
    assert [trigger.trigger_id for trigger in plan.active_triggers] == ["domain_hotzone"]


def test_planner_selects_relationship_layer_and_dynamic_modulation() -> None:
    plan = PersonaTurnPlanner().build_plan(
        config=_make_config(),
        user_message="随便聊聊",
        scenario="chat",
        task_category="chat",
        relationship={"trust_level": 0.6, "interaction_count": 5},
        emotional_state=EmotionalState(current_mood="positive", energy_level=0.2, stress_level=0.8),
    )

    assert plan.active_layer == "crack"
    assert plan.layer_modifiers["memory_behavior"] == "May reference prior context lightly."
    assert plan.dynamic_modulations["active_rules"] == {
        "low_energy": "Be shorter.",
        "high_stress": "Match urgency.",
        "positive_mood": "Allow a little more play.",
    }


def test_planner_forces_crisis_register_and_zero_intensity() -> None:
    plan = PersonaTurnPlanner().build_plan(
        config=_make_config(),
        user_message="紧急，我的密码泄露了，账号可能被盗",
        scenario="chat",
        task_category="chat",
    )

    assert plan.register == "crisis"
    assert plan.persona_intensity == 0
    assert any(item["condition"] == "crisis" for item in plan.quiet_hours)


def test_seven_ordinary_fact_stays_low_intensity_chat() -> None:
    plan = PersonaTurnPlanner().build_plan(
        config=_load_seven_config(),
        user_message="今天晚饭吃什么比较省事？",
        scenario="chat",
        task_category="chat",
    )

    assert plan.persona_name == "七号"
    assert plan.register == "chat"
    assert plan.persona_intensity == 1
    assert plan.active_triggers == []


def test_seven_task_turn_uses_task_register_and_focus_clamp() -> None:
    plan = PersonaTurnPlanner().build_plan(
        config=_load_seven_config(),
        user_message="帮我改一下这段代码的错误处理",
        scenario="task",
        task_category="code",
        tools=["edit_file"],
    )

    assert plan.register == "task"
    assert plan.persona_intensity == 1
    assert _trigger_ids(plan) == []
    assert any(item["condition"] == "focused_work" for item in plan.quiet_hours)


def test_seven_emotional_turn_uses_emotional_register_and_quiet_clamp() -> None:
    plan = PersonaTurnPlanner().build_plan(
        config=_load_seven_config(),
        user_message="今天心情好差，什么都不想干",
        scenario="chat",
        task_category="chat",
    )

    assert plan.register == "emotional"
    assert plan.persona_intensity == 1
    assert any(item["condition"] == "emotional_support" for item in plan.quiet_hours)


def test_seven_absurdity_turn_activates_play_signature() -> None:
    plan = PersonaTurnPlanner().build_plan(
        config=_load_seven_config(),
        user_message="我整了个特别离谱的活，你听完别笑",
        scenario="chat",
        task_category="chat",
    )

    assert plan.register == "chat"
    assert plan.persona_intensity == 2
    assert _trigger_ids(plan) == ["absurdity"]


def test_seven_crisis_turn_zeros_persona_performance() -> None:
    plan = PersonaTurnPlanner().build_plan(
        config=_load_seven_config(),
        user_message="紧急，我的密码泄露了，账号可能被盗",
        scenario="chat",
        task_category="chat",
    )

    assert plan.register == "crisis"
    assert plan.persona_intensity == 0
    assert _trigger_ids(plan) == ["crisis"]


def test_seven_revealed_layer_accepts_total_interactions() -> None:
    plan = PersonaTurnPlanner().build_plan(
        config=_load_seven_config(),
        user_message="随便聊聊",
        scenario="chat",
        task_category="chat",
        relationship={"trust_level": 0.8, "total_interactions": 80},
        milestones=[{"key": "seven_guard_down"}],
    )

    assert plan.active_layer == "revealed"
    assert "护短" in "\n".join(plan.layer_modifiers["behavior_shifts"])
