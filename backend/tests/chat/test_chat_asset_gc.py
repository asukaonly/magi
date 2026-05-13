from __future__ import annotations

import os
from importlib import import_module
from pathlib import Path

import pytest

from magi.chat.asset_gc import ChatAssetGC
from magi.core.sqlite import sqlite_connection_async
from magi.utils.runtime import RuntimePaths


chat_initial = import_module("magi.db.migrations.chat.versions.0001_initial")


def _write_asset(root: Path, session_id: str, turn_id: str, filename: str) -> Path:
    path = root / session_id / turn_id / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("asset", encoding="utf-8")
    return path


def _touch_tree(path: Path, timestamp: float) -> None:
    for child in path.rglob("*"):
        os.utime(child, (timestamp, timestamp))
    os.utime(path, (timestamp, timestamp))


def test_chat_asset_gc_deletes_all_session_asset_roots(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path)
    gc = ChatAssetGC(runtime_paths=runtime_paths)

    _write_asset(runtime_paths.chat_images_dir, "session-1", "turn-1", "image.png")
    _write_asset(runtime_paths.chat_files_dir, "session-1", "turn-1", "file.txt")
    _write_asset(runtime_paths.chat_derived_dir, "session-1", "turn-1", "file.txt")
    kept = _write_asset(runtime_paths.chat_files_dir, "session-2", "turn-1", "file.txt")

    result = gc.delete_session_assets("session-1")

    assert result["chat_asset_files_deleted"] == 3
    assert not (runtime_paths.chat_images_dir / "session-1").exists()
    assert not (runtime_paths.chat_files_dir / "session-1").exists()
    assert not (runtime_paths.chat_derived_dir / "session-1").exists()
    assert kept.exists()


@pytest.mark.asyncio
async def test_chat_asset_gc_sweeps_orphans_after_grace_period(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path)
    now = 2_000_000.0
    gc = ChatAssetGC(runtime_paths=runtime_paths, now=lambda: now)
    active = _write_asset(runtime_paths.chat_files_dir, "active-session", "turn-1", "file.txt")
    old_orphan = _write_asset(runtime_paths.chat_files_dir, "old-orphan", "turn-1", "file.txt")
    recent_orphan = _write_asset(runtime_paths.chat_derived_dir, "recent-orphan", "turn-1", "file.txt")
    old_timestamp = now - (48 * 3600)
    recent_timestamp = now - 60
    _touch_tree(old_orphan.parents[1], old_timestamp)
    _touch_tree(recent_orphan.parents[1], recent_timestamp)

    async with sqlite_connection_async(runtime_paths.chat_db_path) as db:
        await db.executescript(chat_initial.SCHEMA_SQL)
        await db.execute(
            """
            INSERT INTO chat_sessions (
                session_id, user_id, title, created_at_ms, updated_at_ms
            ) VALUES ('active-session', 'u1', 'Active', 1, 1)
            """
        )
        await db.commit()

    result = gc.sweep_orphan_session_assets(orphan_grace_hours=24)

    assert result["chat_asset_orphan_sessions_deleted"] == 1
    assert result["chat_asset_orphan_files_deleted"] == 1
    assert active.exists()
    assert not old_orphan.exists()
    assert recent_orphan.exists()