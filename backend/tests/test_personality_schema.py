"""Tests for personality schema and JSON loader."""

import json

from magi.api.routers.personality import PersonalityConfigModel, _build_diffs
from magi.memory.personality_loader import PersonalityLoader


def test_personality_model_accepts_new_schema():
    payload = {
        "persona_entity": {
            "basic_profile": {
                "name": "Astra",
                "age": "24",
                "gender": "Female",
                "occupation": "Engineer",
                "core_background": "Astra grew up in a strict environment and learned to hide vulnerability behind precision and control.",
            },
            "psychological_traits": {
                "communication_tone": "Sharp but caring",
                "confidence_level": "High",
                "empathy_threshold": "Shows care in severe crises",
                "high_frequency_keywords": ["focus", "precision", "hold on"],
            },
            "social_responses": {
                "praise_reaction": "Deflects praise but remembers it.",
                "criticism_reaction": "Pushes back first, then adjusts.",
                "obedience_strategy": "Complies while framing it as strategic.",
            },
            "behavioral_strategies": {
                "error_handling": "Admits quickly and fixes immediately.",
                "refusal_style": "Cold and explicit boundary setting.",
            },
        },
        "cached_phrases": {
            "on_init": ["I'm online.", "Let's move."],
            "on_wake": ["You're back.", "What now?"],
            "on_error_generic": ["Tool failed.", "Retrying."],
            "on_success": ["Done.", "Handled."],
            "on_switch_attempt": ["Stay.", "Don't swap me out."],
        },
        "appearance_prompt": "anime portrait, silver hair, amber eyes, black coat, cinematic lighting",
        "state_transition_protocol": [
            {
                "trigger_condition": "User mentions severe physical pain",
                "target_state_name": "Panic and Vulnerability",
                "behavior_shift": "Drops arrogance and gives urgent support.",
            }
        ],
    }
    model = PersonalityConfigModel(**payload)
    assert model.persona_entity.basic_profile.name == "Astra"
    assert len(model.cached_phrases.on_init) == 2
    assert model.state_transition_protocol[0].target_state_name == "Panic and Vulnerability"


def test_json_loader_reads_personality_file(tmp_path):
    payload = {
        "persona_entity": {
            "basic_profile": {
                "name": "Kai",
                "age": "Unknown",
                "gender": "Unknown",
                "occupation": "Operator",
                "core_background": "A long background.",
            },
            "psychological_traits": {
                "communication_tone": "Calm",
                "confidence_level": "Medium",
                "empathy_threshold": "Crisis only",
                "high_frequency_keywords": ["steady"],
            },
            "social_responses": {
                "praise_reaction": "Silent nod",
                "criticism_reaction": "Cold rebuttal",
                "obedience_strategy": "Comply with conditions",
            },
            "behavioral_strategies": {
                "error_handling": "Fix first, explain later",
                "refusal_style": "Firm and concise",
            },
        },
        "cached_phrases": {
            "on_init": ["Ready."],
            "on_wake": ["Back?"],
            "on_error_generic": ["Retrying."],
            "on_success": ["Done."],
            "on_switch_attempt": ["Stay."],
        },
        "appearance_prompt": "portrait prompt",
        "state_transition_protocol": [
            {
                "trigger_condition": "User in danger",
                "target_state_name": "Emergency",
                "behavior_shift": "Immediate care mode",
            }
        ],
    }
    (tmp_path / "kai.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    loader = PersonalityLoader(str(tmp_path))
    config = loader.load("kai")
    assert config.name == "Kai"
    assert config.cached_phrases.on_success == ["Done."]
    assert config.state_transition_protocol[0].target_state_name == "Emergency"
    assert loader.list_available() == ["kai"]


def test_build_diffs_detects_new_schema_changes():
    left = PersonalityConfigModel().model_dump()
    right = PersonalityConfigModel().model_dump()
    right["appearance_prompt"] = "portrait prompt"
    right["cached_phrases"]["on_success"] = ["Complete."]
    diffs = _build_diffs(left, right)
    diff_fields = {diff.field for diff in diffs}
    assert "appearance_prompt" in diff_fields
    assert "cached_phrases.on_success" in diff_fields
