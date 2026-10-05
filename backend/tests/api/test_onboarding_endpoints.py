"""Tests for onboarding-related endpoints."""

import json
from pathlib import Path

from magi.api.routers.personality_presets import _parse_json_preset


def test_parse_json_preset(tmp_path: Path):
    file_path = tmp_path / "helper.json"
    file_path.write_text(
        json.dumps({
            "meta": {"group": "general", "order": 1},
            "name": "Helper",
            "description": "A practical helper",
            "identity_core": {
                "identity_statement": "Use concise and direct responses.",
            },
        }),
        encoding="utf-8",
    )
    preset = _parse_json_preset(file_path)
    assert preset.id == "helper"
    assert preset.name == "Helper"
    assert preset.description == "A practical helper"
    assert "Use concise" in preset.prompt
