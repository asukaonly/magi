"""Tests for PersonaRepository and persona seed service."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio

from magi.personality.persona_repository import PersonaRepository, PersonaSummary
from magi.personality import persona_seed


_SAMPLE_CONFIG = json.dumps({
    "meta": {"group": "test", "order": 5},
    "name": "Test Persona",
    "description": "A test persona",
    "avatar": "test.jpg",
    "identity_core": {"identity_statement": "A test persona."},
})


@pytest_asyncio.fixture
async def repo(tmp_path: Path) -> PersonaRepository:
    db_path = str(tmp_path / "persona_registry.db")
    r = PersonaRepository(db_path)
    await r.init()
    return r


class TestPersonaRepository:
    """CRUD operations on PersonaRepository."""

    @pytest.mark.asyncio
    async def test_create_and_get(self, repo: PersonaRepository) -> None:
        pid = await repo.create(_SAMPLE_CONFIG, locale="en", slug="test_persona")
        assert pid

        record = await repo.get(pid)
        assert record.name == "Test Persona"
        assert record.slug == "test_persona"
        assert record.locale == "en"
        assert record.avatar_path == "test.jpg"
        assert record.group_name == "test"
        assert record.sort_order == 5
        assert not record.is_builtin

    @pytest.mark.asyncio
    async def test_get_by_slug(self, repo: PersonaRepository) -> None:
        pid = await repo.create(_SAMPLE_CONFIG, slug="my_slug")
        record = await repo.get_by_slug("my_slug")
        assert record.persona_id == pid

    @pytest.mark.asyncio
    async def test_get_missing_raises(self, repo: PersonaRepository) -> None:
        with pytest.raises(KeyError):
            await repo.get("nonexistent-id")

    @pytest.mark.asyncio
    async def test_slug_uniqueness(self, repo: PersonaRepository) -> None:
        await repo.create(_SAMPLE_CONFIG, slug="dup")
        pid2 = await repo.create(_SAMPLE_CONFIG, slug="dup")
        record2 = await repo.get(pid2)
        assert record2.slug == "dup_1"

    @pytest.mark.asyncio
    async def test_list_all(self, repo: PersonaRepository) -> None:
        await repo.create(_SAMPLE_CONFIG, slug="a")
        await repo.create(_SAMPLE_CONFIG, slug="b")
        items = await repo.list_all()
        assert len(items) == 2
        assert all(isinstance(s, PersonaSummary) for s in items)

    @pytest.mark.asyncio
    async def test_update(self, repo: PersonaRepository) -> None:
        pid = await repo.create(_SAMPLE_CONFIG, slug="upd")
        await repo.update(pid, name="New Name", sort_order=99)
        record = await repo.get(pid)
        assert record.name == "New Name"
        assert record.sort_order == 99

    @pytest.mark.asyncio
    async def test_update_missing_raises(self, repo: PersonaRepository) -> None:
        with pytest.raises(KeyError):
            await repo.update("bad-id", name="x")

    @pytest.mark.asyncio
    async def test_delete(self, repo: PersonaRepository) -> None:
        pid = await repo.create(_SAMPLE_CONFIG, slug="del")
        await repo.delete(pid)
        assert await repo.count() == 0
        assert await repo.count(include_deleted=True) == 1
        with pytest.raises(KeyError):
            await repo.get(pid)
        deleted = await repo.get(pid, include_deleted=True)
        assert deleted.deleted_at is not None
        assert await repo.list_all() == []
        assert len(await repo.list_all(include_deleted=True)) == 1
        with pytest.raises(KeyError):
            await repo.set_active(pid)

    @pytest.mark.asyncio
    async def test_delete_active_raises(self, repo: PersonaRepository) -> None:
        pid = await repo.create(_SAMPLE_CONFIG, slug="act")
        await repo.set_active(pid)
        with pytest.raises(ValueError, match="active"):
            await repo.delete(pid)

    @pytest.mark.asyncio
    async def test_active_persona_lifecycle(self, repo: PersonaRepository) -> None:
        assert await repo.get_active_id() is None
        pid = await repo.create(_SAMPLE_CONFIG, slug="act2")
        await repo.set_active(pid)
        assert await repo.get_active_id() == pid

    @pytest.mark.asyncio
    async def test_set_active_missing_raises(self, repo: PersonaRepository) -> None:
        with pytest.raises(KeyError):
            await repo.set_active("missing")

    @pytest.mark.asyncio
    async def test_get_by_seed_slug(self, repo: PersonaRepository) -> None:
        pid = await repo.create(
            _SAMPLE_CONFIG,
            slug="echo",
            is_builtin=True,
            seed_slug="echo_ai_ssistant",
        )
        found = await repo.get_by_seed_slug("echo_ai_ssistant")
        assert found is not None
        assert found.persona_id == pid

        not_found = await repo.get_by_seed_slug("nonexistent")
        assert not_found is None

    @pytest.mark.asyncio
    async def test_count(self, repo: PersonaRepository) -> None:
        assert await repo.count() == 0
        await repo.create(_SAMPLE_CONFIG, slug="c1")
        await repo.create(_SAMPLE_CONFIG, slug="c2")
        assert await repo.count() == 2

    @pytest.mark.asyncio
    async def test_config_roundtrip(self, repo: PersonaRepository) -> None:
        """Config stored as JSON can be loaded back as PersonalityConfig."""
        pid = await repo.create(_SAMPLE_CONFIG, slug="rt")
        record = await repo.get(pid)
        assert record.config.name == "Test Persona"
        roundtrip = record.config.to_dict()
        assert roundtrip["name"] == "Test Persona"


@pytest.mark.asyncio
async def test_list_seed_previews_exposes_default_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seed_dir = tmp_path / "en"
    seed_dir.mkdir()
    (seed_dir / "nova_assistant.json").write_text(
        json.dumps(
            {
                "meta": {"group": "general", "order": 1, "default": True},
                "name": "Nova",
                "description": "English default",
                "avatar": "nova.png",
                "identity_core": {
                    "identity_statement": "Nova test persona.",
                },
            }
        ),
        encoding="utf-8",
    )
    (seed_dir / "echo_ai_ssistant.json").write_text(
        json.dumps(
            {
                "meta": {"group": "general", "order": 2, "recommended": True},
                "name": "Echo-01",
                "description": "Chinese default",
                "avatar": "echo.png",
                "identity_core": {
                    "identity_statement": "Echo test persona.",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(persona_seed, "_seed_dir", lambda _locale: seed_dir)

    previews = await persona_seed.list_seed_previews("en")

    assert previews[0]["seed_slug"] == "nova_assistant"
    assert previews[0]["is_default"] is True
    assert previews[1]["is_recommended"] is True
