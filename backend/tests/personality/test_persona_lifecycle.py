"""Regression coverage for synchronizing installed persona language bundles."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from magi.bootstrap.context import RuntimeBootstrapContext
from magi.core.initialization_state import InitializationStateStore
from magi.personality import lifecycle, persona_seed
from magi.personality.persona_repository import PersonaRepository
from magi.utils.runtime import get_runtime_paths


def _write_seed(root: Path, locale: str, name: str, avatar: str) -> None:
    directory = root / locale
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.json").write_text(json.dumps({
        "name": name,
        "avatar": avatar,
        "identity_core": {"identity_statement": "A reliable assistant."},
    }), encoding="utf-8")


async def _startup_context(tmp_path: Path, monkeypatch):
    paths = get_runtime_paths()
    repo = PersonaRepository(str(paths.persona_registry_db_path))
    await repo.init()
    state = InitializationStateStore(tmp_path / "initialization.db")
    await state.initialize()
    context = RuntimeBootstrapContext()
    context.core.runtime_paths = paths
    context.core.initialization_state = state
    monkeypatch.setattr(lifecycle, "SelfMemory", Mock(return_value=SimpleNamespace(init=AsyncMock())))
    monkeypatch.setattr(lifecycle, "set_current_personality", Mock())
    return repo, state, context


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["zh-CN", "en"])
async def test_startup_updates_installed_other_language_avatars_without_changing_active_persona(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    root = tmp_path / "seeds"
    monkeypatch.setattr(persona_seed, "_seed_dir", lambda locale: root / locale)
    monkeypatch.setattr(lifecycle, "get_preferred_language", lambda: language)
    repo, state, context = await _startup_context(tmp_path, monkeypatch)
    for locale, name in (("zh", "echo"), ("en", "nova")):
        _write_seed(root, locale, name, f"{name}.png")
        await persona_seed.sync_builtin_personas(repo, locale, state)
    before = {item.seed_slug: await repo.get(item.persona_id) for item in await repo.list_all()}
    active_name = "nova" if language == "zh-CN" else "echo"
    active_id = before[active_name].persona_id
    await repo.set_active(active_id)
    for locale, name in (("zh", "echo"), ("en", "nova")):
        _write_seed(root, locale, name, f"{name}.svg")

    module = lifecycle.PersonalityModule(context)
    await module.init()

    for name, old_record in before.items():
        record = await repo.get(old_record.persona_id)
        assert record.avatar_path == f"{name}.svg"
        assert record.updated_at > old_record.updated_at
    assert await repo.get_active_id() == active_id
    assert context.core.current_personality == active_name
    assert lifecycle.set_current_personality.call_args.kwargs["config"].avatar == f"{active_name}.svg"

    after = {item.persona_id: await repo.get(item.persona_id) for item in await repo.list_all()}
    await module.init()
    assert {item.persona_id: await repo.get(item.persona_id) for item in await repo.list_all()} == after


@pytest.mark.asyncio
async def test_startup_does_not_install_other_language_for_a_custom_persona(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "seeds"
    monkeypatch.setattr(persona_seed, "_seed_dir", lambda locale: root / locale)
    monkeypatch.setattr(lifecycle, "get_preferred_language", lambda: "zh-CN")
    repo, _state, context = await _startup_context(tmp_path, monkeypatch)
    _write_seed(root, "zh", "echo", "echo.svg")
    _write_seed(root, "en", "nova", "nova.svg")
    custom_id = await repo.create(json.dumps({
        "name": "Custom",
        "avatar": "/static/user-avatars/custom.png",
        "identity_core": {"identity_statement": "A custom persona."},
    }), locale="en")
    await repo.set_active(custom_id)
    before = await repo.get(custom_id)

    await lifecycle.PersonalityModule(context).init()

    builtins = [item for item in await repo.list_all() if item.is_builtin]
    assert [item.seed_slug for item in builtins] == ["echo"]
    assert await repo.get(custom_id) == before
    assert await repo.get_active_id() == custom_id
