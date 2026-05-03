"""Tests for personality schema and JSON loader."""

import json
from pathlib import Path

from magi.api.routers.personality_config import PersonalityConfigModel, _build_diffs
from magi.personality.loader import PersonalityLoader


REQUIRED_PERSONA_REGISTERS = ("chat", "analysis", "task", "emotional", "crisis")


def test_personality_model_accepts_new_schema():
    payload = {
        "name": "Astra",
        "description": "Sharp but caring engineer.",
        "identity_core": {
            "identity_statement": "Astra grew up in a strict environment and learned to hide vulnerability behind precision and control.",
            "attention_biases": ["focus", "precision"],
        },
        "idiolect": {"sentence_style": "Sharp but caring"},
        "appearance_prompt": "anime portrait, silver hair, amber eyes, black coat, cinematic lighting",
        "signature_triggers": [
            {
                "trigger_id": "crisis",
                "activates_when": "User mentions severe physical pain",
                "behavior_shift": "Drops arrogance and gives urgent support.",
            }
        ],
    }
    model = PersonalityConfigModel(**payload)
    assert model.name == "Astra"
    assert model.signature_triggers[0].trigger_id == "crisis"


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
    (tmp_path / "kai.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    loader = PersonalityLoader(str(tmp_path))
    config = loader.load("kai")
    assert config.name == "Kai"
    assert config.signature_triggers[0].behavior_shift == "Immediate care mode"
    assert loader.list_available() == ["kai"]


def test_build_diffs_detects_new_schema_changes():
    left = PersonalityConfigModel().model_dump()
    right = PersonalityConfigModel().model_dump()
    right["identity_core"]["identity_statement"] = "A different core."
    diffs = _build_diffs(left, right)
    diff_fields = {diff.field for diff in diffs}
    assert "identity_core.identity_statement" in diff_fields


def test_builtin_personality_presets_are_editor_ready():
    preset_root = Path(__file__).resolve().parents[2] / "personalities"
    preset_files = sorted((preset_root / "en").glob("*.json")) + sorted((preset_root / "zh").glob("*.json"))

    assert preset_files

    for preset_file in preset_files:
        payload = json.loads(preset_file.read_text(encoding="utf-8"))
        registers = payload.get("registers") or {}
        assert all(
            key in registers and registers[key].get("description") and registers[key].get("behavior")
            for key in REQUIRED_PERSONA_REGISTERS
        ), preset_file.name
        assert len(payload.get("quiet_hours") or []) >= 2, preset_file.name
        assert len(payload.get("signature_triggers") or []) >= 2, preset_file.name

        example_count = sum(len((registers.get(key) or {}).get("examples") or []) for key in REQUIRED_PERSONA_REGISTERS)
        assert example_count >= 6, preset_file.name

        rendered_behaviors = "\n".join(str((registers.get(key) or {}).get("behavior") or "") for key in REQUIRED_PERSONA_REGISTERS)
        assert "Scenario Behavioral Protocol" not in rendered_behaviors, preset_file.name
        assert "System Notice" not in rendered_behaviors, preset_file.name
        assert "MUST" not in rendered_behaviors, preset_file.name
