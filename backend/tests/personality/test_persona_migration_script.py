from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from magi.personality.persona_repository import PersonaRepository


def _load_migration_script(root: Path) -> ModuleType:
    script_path = root / "scripts" / "migrate-personas-to-registry.py"
    spec = importlib.util.spec_from_file_location("persona_migration_script", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _persona_payload(name: str) -> str:
    return json.dumps(
        {
            "meta": {"group": "legacy", "order": 2},
            "persona_entity": {
                "basic_profile": {
                    "name": name,
                    "description": f"{name} description",
                    "avatar": f"{name.lower()}.png",
                },
            },
        },
        ensure_ascii=False,
    )


@pytest.mark.asyncio
async def test_migrates_legacy_persona_files_idempotently(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    migration = _load_migration_script(root)
    source_dir = tmp_path / "personalities"
    source_dir.mkdir()
    (source_dir / "nova.json").write_text(_persona_payload("Nova"), encoding="utf-8")
    (source_dir / "broken.json").write_text("{", encoding="utf-8")
    db_path = tmp_path / "persona_registry.db"

    first = await migration.import_persona_directory(
        source_dir=source_dir,
        db_path=db_path,
        locale="en",
        set_active_slug="nova",
    )
    second = await migration.import_persona_directory(
        source_dir=source_dir,
        db_path=db_path,
        locale="en",
    )

    repo = PersonaRepository(str(db_path))
    await repo.init()
    record = await repo.get_by_slug("nova")

    assert first.imported == 1
    assert first.skipped_existing == 0
    assert first.invalid == 1
    assert first.active_persona_id == record.persona_id
    assert second.imported == 0
    assert second.skipped_existing == 1
    assert second.invalid == 1
    assert await repo.count() == 1
    assert await repo.get_active_id() == record.persona_id
    assert record.locale == "en"
    assert record.name == "Nova"


@pytest.mark.asyncio
async def test_dry_run_does_not_create_registry(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    migration = _load_migration_script(root)
    source_dir = tmp_path / "personalities"
    source_dir.mkdir()
    (source_dir / "ember.json").write_text(_persona_payload("Ember"), encoding="utf-8")
    db_path = tmp_path / "persona_registry.db"

    report = await migration.import_persona_directory(
        source_dir=source_dir,
        db_path=db_path,
        locale="en",
        dry_run=True,
    )

    assert report.imported == 1
    assert report.skipped_existing == 0
    assert report.invalid == 0
    assert not db_path.exists()