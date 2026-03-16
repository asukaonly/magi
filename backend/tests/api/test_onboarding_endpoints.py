"""Tests for onboarding-related endpoints."""

import json
from pathlib import Path

from magi.api.routers.personality_presets import _parse_json_preset
from magi.skills.service_access import _get_enabled_skill_names


def test_parse_json_preset(tmp_path: Path):
    file_path = tmp_path / "helper.json"
    file_path.write_text(
        json.dumps({
            "meta": {"group": "general", "order": 1},
            "persona_entity": {
                "basic_profile": {
                    "name": "Helper",
                    "occupation": "A practical helper",
                    "core_background": "Use concise and direct responses.",
                }
            },
        }),
        encoding="utf-8",
    )
    preset = _parse_json_preset(file_path)
    assert preset.id == "helper"
    assert preset.name == "Helper"
    assert preset.occupation == "A practical helper"
    assert "Use concise" in preset.prompt


def test_get_enabled_skill_names(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "magi.skills.service_access.get_config",
        lambda: type("Config", (), {"tools": type("Tools", (), {"skills": ["skill-a", "skill-b"]})()})(),
    )
    names = _get_enabled_skill_names()
    assert names == {"skill-a", "skill-b"}
