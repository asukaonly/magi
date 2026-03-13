"""Tests for onboarding-related endpoints."""

from pathlib import Path

import yaml

from magi.api.routers.personalities import _parse_markdown_preset
from magi.api.routers.skills import _get_enabled_skill_names


def test_parse_markdown_preset(tmp_path: Path):
    file_path = tmp_path / "helper.md"
    file_path.write_text(
        "# Helper\n\nA practical helper.\n\nUse concise and direct responses.",
        encoding="utf-8",
    )
    preset = _parse_markdown_preset(file_path)
    assert preset.id == "helper"
    assert preset.name == "Helper"
    assert preset.description == "A practical helper."
    assert "Use concise" in preset.prompt


def test_get_enabled_skill_names(monkeypatch, tmp_path: Path):
    config_file = tmp_path / "agent.yaml"
    config_file.write_text(
        yaml.safe_dump(
            {
                "tools": {
                    "skills": ["skill-a", "skill-b"],
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "magi.api.routers.skills.get_config_file_path",
        lambda: config_file,
    )
    names = _get_enabled_skill_names()
    assert names == {"skill-a", "skill-b"}

