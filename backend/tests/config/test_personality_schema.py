"""Tests for personality schema and JSON loader."""

import json

from magi.api.routers.personality_config import PersonalityConfigModel, _build_diffs
from magi.personality.loader import PersonalityLoader


def test_personality_model_accepts_new_schema():
    payload = {
        "persona_entity": {
            "basic_profile": {
                "name": "Astra",
                "age": "24",
                "gender": "Female",
                "occupation": "Engineer",
            },
            "core_identity": {
                "inner_narrative": "Astra grew up in a strict environment and learned to hide vulnerability behind precision and control.",
                "language_fingerprint": "Sharp but caring",
                "attention_bias": "focus, precision, hold on",
            },
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
    assert model.state_transition_protocol[0].target_state_name == "Panic and Vulnerability"


def test_json_loader_reads_personality_file(tmp_path):
    payload = {
        "persona_entity": {
            "basic_profile": {
                "name": "Kai",
                "age": "Unknown",
                "gender": "Unknown",
                "occupation": "Operator",
            },
            "core_identity": {
                "inner_narrative": "A long background.",
                "language_fingerprint": "Calm",
                "attention_bias": "",
            },
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
    assert config.state_transition_protocol[0].target_state_name == "Emergency"
    assert loader.list_available() == ["kai"]


def test_build_diffs_detects_new_schema_changes():
    left = PersonalityConfigModel().model_dump()
    right = PersonalityConfigModel().model_dump()
    right["appearance_prompt"] = "portrait prompt"
    diffs = _build_diffs(left, right)
    diff_fields = {diff.field for diff in diffs}
    assert "appearance_prompt" in diff_fields
