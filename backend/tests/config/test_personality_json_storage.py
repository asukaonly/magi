"""Tests for personality registry storage behavior."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from magi.api.routers.personality_config import (
    PersonalityConfigModel,
    delete_personality,
    list_personalities,
    save_personality_to_registry,
)


@pytest.mark.asyncio
async def test_save_personality_to_registry_creates_new():
    mock_repo = AsyncMock()
    mock_repo.init = AsyncMock()
    mock_repo.get_by_slug = AsyncMock(side_effect=KeyError("not found"))
    mock_repo.create = AsyncMock(return_value="pid_001")

    with patch("magi.api.routers.personality_config.PersonaRepository", return_value=mock_repo):
        with patch("magi.api.routers.personality_config.get_runtime_paths") as mock_paths:
            mock_paths.return_value.persona_registry_db_path = "/tmp/test/persona.db"
            slug = await save_personality_to_registry("test_persona", PersonalityConfigModel())

    assert slug == "test_persona"
    mock_repo.create.assert_called_once()


@pytest.mark.asyncio
async def test_save_personality_to_registry_updates_existing():
    mock_record = MagicMock()
    mock_record.persona_id = "pid_001"
    mock_repo = AsyncMock()
    mock_repo.init = AsyncMock()
    mock_repo.get_by_slug = AsyncMock(return_value=mock_record)
    mock_repo.update = AsyncMock()

    with patch("magi.api.routers.personality_config.PersonaRepository", return_value=mock_repo):
        with patch("magi.api.routers.personality_config.get_runtime_paths") as mock_paths:
            mock_paths.return_value.persona_registry_db_path = "/tmp/test/persona.db"
            slug = await save_personality_to_registry("test_persona", PersonalityConfigModel())

    assert slug == "test_persona"
    mock_repo.update.assert_called_once()


@pytest.mark.asyncio
async def test_list_personalities_from_registry():
    summary1 = MagicMock()
    summary1.slug = "persona_a"
    summary2 = MagicMock()
    summary2.slug = "persona_b"
    mock_repo = AsyncMock()
    mock_repo.init = AsyncMock()
    mock_repo.list_all = AsyncMock(return_value=[summary1, summary2])

    with patch("magi.api.routers.personality_config.PersonaRepository", return_value=mock_repo):
        with patch("magi.api.routers.personality_config.get_runtime_paths") as mock_paths:
            mock_paths.return_value.persona_registry_db_path = "/tmp/test/persona.db"
            result = await list_personalities()

    assert result.success is True
    assert "persona_a" in result.data["personalities"]
    assert "persona_b" in result.data["personalities"]


@pytest.mark.asyncio
async def test_delete_personality_from_registry():
    mock_repo = AsyncMock()
    mock_repo.init = AsyncMock()
    mock_repo.delete = AsyncMock()

    with patch("magi.api.routers.personality_config.PersonaRepository", return_value=mock_repo):
        with patch("magi.api.routers.personality_config.get_runtime_paths") as mock_paths:
            mock_paths.return_value.persona_registry_db_path = "/tmp/test/persona.db"
            result = await delete_personality("test_persona")

    assert result.success is True
    mock_repo.delete.assert_called_once()
