"""Tests for PersonaRepository and persona seed service."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import uuid

import pytest
import pytest_asyncio

from magi.personality.persona_repository import PersonaRepository, PersonaSummary
from magi.personality.reference_research.models import ReferenceDossier, ReferenceIdentity
from magi.personality import persona_seed


_SAMPLE_CONFIG = json.dumps({
    "meta": {"group": "test", "order": 5},
    "name": "Test Persona",
    "description": "A test persona",
    "avatar": "test.jpg",
    "identity_core": {"identity_statement": "A test persona."},
})


def _reference_dossier() -> ReferenceDossier:
    return ReferenceDossier(
        reference_fingerprint="reference-fingerprint",
        identity_status="verified",
        grounding_status="verified",
        research_level="representative",
        canonical_identity=ReferenceIdentity(
            source_kind="fictional_reference",
            name="Reference",
            work_title="Example Work",
        ),
        sufficient=True,
    )


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
    async def test_create_with_same_persona_id_is_idempotent_under_concurrency(
        self,
        repo: PersonaRepository,
    ) -> None:
        persona_id = str(uuid.uuid4())

        first_id, second_id = await asyncio.gather(
            repo.create(
                _SAMPLE_CONFIG,
                locale="en",
                slug="stable-custom",
                persona_id=persona_id,
            ),
            repo.create(
                _SAMPLE_CONFIG,
                locale="en",
                slug="stable-custom",
                persona_id=persona_id,
            ),
        )
        repeated_id = await repo.create(
            _SAMPLE_CONFIG,
            locale="en",
            slug="stable-custom",
            persona_id=persona_id,
        )

        assert first_id == second_id == repeated_id == persona_id
        assert await repo.count() == 1
        assert (await repo.get(persona_id)).slug == "stable-custom"

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
            seed_slug="echo_ai_assistant",
        )
        found = await repo.get_by_seed_slug("echo_ai_assistant")
        assert found is not None
        assert found.persona_id == pid

        not_found = await repo.get_by_seed_slug("nonexistent")
        assert not_found is None

        summaries = await repo.list_all()
        assert summaries[0].seed_slug == "echo_ai_assistant"

    @pytest.mark.asyncio
    async def test_ensure_active_persona_resolves_display_name(self, repo: PersonaRepository) -> None:
        from magi.personality.lifecycle import _ensure_active_persona

        pid = await repo.create(
            json.dumps(
                {
                    "name": "七号",
                    "description": "赛博乐子人",
                    "identity_core": {"identity_statement": "测试设定。"},
                }
            ),
            slug="seven_hacker",
            is_builtin=True,
            seed_slug="seven_hacker",
        )

        active_id = await _ensure_active_persona(repo, "七号")

        assert active_id == pid
        assert await repo.get_active_id() == pid

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
    async def test_reference_dossier_roundtrip_and_idempotent_refresh(
        self,
        repo: PersonaRepository,
    ) -> None:
        persona_id = str(uuid.uuid4())
        dossier = _reference_dossier()
        await repo.create(
            _SAMPLE_CONFIG,
            slug="grounded",
            persona_id=persona_id,
            reference_dossier_json=dossier.model_dump_json(),
        )

        stored = await repo.get_reference_dossier(persona_id)
        assert stored is not None
        assert stored.reference_fingerprint == "reference-fingerprint"

        refreshed = dossier.model_copy(update={"grounding_status": "insufficient", "sufficient": False})
        await repo.create(
            _SAMPLE_CONFIG,
            slug="grounded",
            persona_id=persona_id,
            reference_dossier_json=refreshed.model_dump_json(),
        )

        stored = await repo.get_reference_dossier(persona_id)
        assert stored is not None
        assert stored.grounding_status == "insufficient"
        assert await repo.count() == 1


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
    (seed_dir / "echo_ai_assistant.json").write_text(
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


@pytest.mark.asyncio
async def test_seed_builtin_personas_syncs_existing_seed_config(
    repo: PersonaRepository,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_dir = tmp_path / "zh"
    seed_dir.mkdir()
    preset_path = seed_dir / "seven_hacker.json"
    preset_path.write_text(
        json.dumps(
            {
                "meta": {"group": "magi", "order": 1},
                "name": "七号",
                "description": "旧描述",
                "avatar": "seven.png",
                "identity_core": {"identity_statement": "旧设定。"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(persona_seed, "_seed_dir", lambda _locale: seed_dir)

    created_ids = await persona_seed.seed_builtin_personas(repo, "zh")
    assert len(created_ids) == 1

    preset_path.write_text(
        json.dumps(
            {
                "meta": {"group": "general", "order": 7},
                "name": "七号",
                "description": "新描述",
                "avatar": "seven-new.png",
                "identity_core": {"identity_statement": "新设定。"},
            }
        ),
        encoding="utf-8",
    )

    second_created_ids = await persona_seed.seed_builtin_personas(repo, "zh")
    record = await repo.get_by_seed_slug("seven_hacker")

    assert second_created_ids == []
    assert record is not None
    assert record.config.description == "新描述"
    assert record.avatar_path == "seven-new.png"
    assert record.group_name == "general"
    assert record.sort_order == 7
    assert record.config.identity_core.identity_statement == "新设定。"


@pytest.mark.asyncio
async def test_seed_builtin_personas_is_idempotent_under_concurrency(
    repo: PersonaRepository,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_dir = tmp_path / "en"
    seed_dir.mkdir()
    (seed_dir / "nova_assistant.json").write_text(
        json.dumps(
            {
                "meta": {"group": "general", "order": 1},
                "name": "Nova",
                "description": "Concurrent seed",
                "avatar": "nova.png",
                "identity_core": {"identity_statement": "Nova test persona."},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(persona_seed, "_seed_dir", lambda _locale: seed_dir)

    original_get = repo.get_by_seed_slug
    both_lookups_finished = asyncio.Event()
    missing_lookup_count = 0

    async def synchronized_get(seed_slug: str, *, include_deleted: bool = False):
        nonlocal missing_lookup_count
        existing = await original_get(seed_slug, include_deleted=include_deleted)
        if existing is None:
            missing_lookup_count += 1
            if missing_lookup_count == 2:
                both_lookups_finished.set()
            await both_lookups_finished.wait()
        return existing

    monkeypatch.setattr(repo, "get_by_seed_slug", synchronized_get)

    first_result, second_result = await asyncio.gather(
        persona_seed.seed_builtin_personas(repo, "en"),
        persona_seed.seed_builtin_personas(repo, "en"),
    )

    records = [
        item
        for item in await repo.list_all()
        if item.is_builtin and item.seed_slug == "nova_assistant"
    ]
    assert len(records) == 1
    assert len(first_result) + len(second_result) == 1
