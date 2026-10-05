"""Tests for personality schema and JSON loader."""

import json
from pathlib import Path

from magi.api.routers.personality_config import PersonalityConfigModel, _build_diffs
from magi.personality.loader import PersonalityLoader


def test_json_loader_reads_personality_file(tmp_path):
    payload = {
        "name": "Kai",
        "description": "Calm operator persona.",
        "avatar": "portrait.png",
        "appearance_prompt": "portrait prompt",
        "identity_core": {
            "identity_statement": "A long background.",
            "attention_biases": ["risk", "clarity"],
        },
        "idiolect": {
            "sentence_style": "Calm",
        },
        "signature_triggers": [
            {
                "trigger_id": "danger",
                "activates_when": "User in danger",
                "behavior_shift": "Immediate care mode",
            }
        ],
    }
    validated = PersonalityConfigModel.model_validate(payload)
    (tmp_path / "kai.json").write_text(validated.model_dump_json(), encoding="utf-8")

    loader = PersonalityLoader(str(tmp_path))
    config = loader.load("kai")
    assert config.name == "Kai"
    assert config.signature_triggers[0].behavior_shift == "Immediate care mode"
    assert loader.list_available() == ["kai"]

    assert config.to_dict() == validated.model_dump()


def test_personality_diffs_preserve_changed_values_and_exclude_unchanged_fields():
    left = PersonalityConfigModel(
        identity_core={"identity_statement": "Original identity", "values_loved": ["clarity"]}
    ).model_dump()
    right = PersonalityConfigModel.model_validate(left).model_dump()
    right["identity_core"]["identity_statement"] = "A different core."
    assert [diff.model_dump() for diff in _build_diffs(left, right)] == [
        {
            "field": "identity_core.identity_statement",
            "field_label": "Identity Statement",
            "old_value": "Original identity",
            "new_value": "A different core.",
        }
    ]
    assert _build_diffs(left, left) == []
    assert left["identity_core"]["identity_statement"] == "Original identity"


def test_builtin_personalities_load_validate_and_render_required_registers():
    from magi.context.renderer import PromptContextRenderer
    from magi.personality.turn_planner import PersonaTurnPlanner

    preset_root = Path(__file__).resolve().parents[2] / "personalities"
    files = sorted((preset_root / "en").glob("*.json")) + sorted(
        (preset_root / "zh").glob("*.json")
    )
    assert files
    scenarios = [
        ("chat", "hello", "chat"),
        ("analysis", "look at this design", "analysis"),
        ("task", "do this work", "task"),
        ("emotional", "I feel sad", "chat"),
        ("crisis", "emergency", "chat"),
    ]
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        validated = PersonalityConfigModel.model_validate(payload)
        config = PersonalityLoader(str(path.parent)).load(path.stem)
        assert config.name == validated.name, path.name
        for register, message, scenario in scenarios:
            definition = validated.registers[register]
            assert definition.description and definition.behavior, (path.name, register)
            plan = PersonaTurnPlanner().build_plan(
                config=config, user_message=message, scenario=scenario, task_category="chat"
            )
            # Some presets prefer their optional casual register for ordinary chat.
            selected = "casual" if register == "chat" and "casual" in config.registers else register
            assert plan.register == selected, (path.name, register)
            assert plan.register_behavior == config.registers[selected].behavior
            rendered = "\n".join(PromptContextRenderer()._render_persona_turn_steer(plan))
            assert plan.register_behavior in rendered, (path.name, register)
            if register == "crisis":
                assert plan.register_is_hard_clamp and plan.persona_intensity == 0
