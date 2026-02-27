"""Tests for personality JSON storage behavior."""

import pytest

from magi.api.routers.personality import (
    PersonalityConfigModel,
    delete_personality,
    list_personalities,
    save_personality_file,
)
from magi.utils.runtime import get_runtime_paths, set_runtime_dir


def test_runtime_personality_file_uses_json_suffix(tmp_path):
    original_base = get_runtime_paths().base_dir
    try:
        set_runtime_dir(tmp_path)
        file_path = get_runtime_paths().personality_file("demo")
        assert file_path.name == "demo.json"
    finally:
        set_runtime_dir(original_base)


@pytest.mark.asyncio
async def test_list_and_delete_personality_use_json_files(tmp_path):
    original_base = get_runtime_paths().base_dir
    try:
        set_runtime_dir(tmp_path)
        payload = PersonalityConfigModel()
        payload.persona_entity.basic_profile.name = "Json Persona"
        assert save_personality_file("json_persona", payload) is True

        saved_path = get_runtime_paths().personalities_dir / "json_persona.json"
        assert saved_path.exists()

        list_result = await list_personalities()
        assert "json_persona" in list_result.data["personalities"]

        delete_result = await delete_personality("json_persona")
        assert delete_result.success is True
        assert not saved_path.exists()
    finally:
        set_runtime_dir(original_base)
