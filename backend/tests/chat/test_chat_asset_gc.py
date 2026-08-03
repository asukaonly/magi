from __future__ import annotations

import os
from importlib import import_module
from pathlib import Path

import pytest

from magi.chat.asset_gc import ChatAssetDeletionError, ChatAssetGC
from magi.chat.attachment_ingestion import LocalChatAttachmentIngestionService
from magi.core.chat_assets.mutations import run_chat_asset_mutation
from magi.core.sqlite import sqlite_connection_async
from magi.utils.runtime import RuntimePaths

chat_initial = import_module("magi.db.migrations.chat.versions.v1_initial")


def _write_asset(root: Path, session_id: str, turn_id: str, filename: str) -> Path:
    path = root / session_id / turn_id / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("asset", encoding="utf-8")
    return path


def _touch_tree(path: Path, timestamp: float) -> None:
    for child in path.rglob("*"):
        os.utime(child, (timestamp, timestamp))
    os.utime(path, (timestamp, timestamp))


async def _initialize_chat_asset_owners(
    runtime_paths: RuntimePaths,
    *,
    active_session_ids: tuple[str, ...],
    owners: tuple[tuple[str, Path, bool], ...] = (),
) -> None:
    async with sqlite_connection_async(runtime_paths.chat_db_path) as db:
        await db.executescript(chat_initial.SCHEMA_SQL)
        for session_id in active_session_ids:
            await db.execute(
                """
                INSERT INTO chat_sessions (
                    session_id, user_id, title, created_at_ms, updated_at_ms
                ) VALUES (?, 'u1', 'Active', 1, 1)
                """,
                (session_id,),
            )
        for index, (message_id, asset_path, is_visible) in enumerate(owners, start=1):
            asset_key = asset_path.relative_to(
                runtime_paths.chat_resources_dir,
            ).as_posix()
            parts = asset_key.split("/")
            session_id, turn_id = parts[1], parts[2]
            await db.execute(
                """
                INSERT INTO chat_messages (
                    message_id, session_id, turn_id, user_id, role,
                    message_kind, content_text, payload_json, is_final,
                    is_visible, created_at_ms, sequence_no
                ) VALUES (?, ?, ?, 'u1', 'user', 'user_text', 'kept', '{}',
                          1, ?, 1, ?)
                """,
                (message_id, session_id, turn_id, 1 if is_visible else 0, index),
            )
            await db.execute(
                """
                INSERT INTO chat_message_asset_refs (
                    message_id, asset_key, storage_rel_path, asset_kind,
                    created_at_ms
                ) VALUES (?, ?, ?, 'attachment', 1)
                """,
                (
                    message_id,
                    asset_key,
                    asset_path.relative_to(runtime_paths.base_dir).as_posix(),
                ),
            )
        await db.commit()


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


def test_chat_asset_gc_deletes_only_selected_message_files(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path)
    gc = ChatAssetGC(runtime_paths=runtime_paths)
    deleted = _write_asset(
        runtime_paths.chat_files_dir,
        "session-1",
        "turn-1",
        "deleted.txt",
    )
    kept = _write_asset(
        runtime_paths.chat_files_dir,
        "session-1",
        "turn-1",
        "kept.txt",
    )

    count = gc.delete_message_assets(
        [
            (
                deleted.relative_to(runtime_paths.chat_resources_dir).as_posix(),
                deleted.relative_to(runtime_paths.base_dir).as_posix(),
            )
        ]
    )

    assert count == 1
    assert not deleted.exists()
    assert kept.exists()


def test_chat_asset_gc_retry_accepts_an_already_removed_asset_scope(
    tmp_path: Path,
) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path)
    gc = ChatAssetGC(runtime_paths=runtime_paths)
    deleted = _write_asset(
        runtime_paths.chat_files_dir,
        "session-1",
        "turn-1",
        "deleted.txt",
    )
    reference = (
        deleted.relative_to(runtime_paths.chat_resources_dir).as_posix(),
        deleted.relative_to(runtime_paths.base_dir).as_posix(),
    )

    assert gc.delete_message_assets([reference]) == 1
    assert not deleted.exists()

    assert gc.delete_message_assets([reference]) == 0


def test_chat_asset_gc_rejects_message_file_outside_managed_storage(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path)
    gc = ChatAssetGC(runtime_paths=runtime_paths)
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")

    with pytest.raises(ChatAssetDeletionError, match="outside managed chat storage"):
        gc.delete_message_assets(
            [
                (
                    "outside.txt",
                    outside.relative_to(runtime_paths.base_dir).as_posix(),
                )
            ]
        )

    assert outside.exists()


def test_chat_asset_gc_rejects_casefold_session_alias_before_deleting_any_root(
    tmp_path: Path,
) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path)
    gc = ChatAssetGC(runtime_paths=runtime_paths)
    exact = _write_asset(
        runtime_paths.chat_images_dir,
        "session-1",
        "turn-1",
        "exact.png",
    )
    alias = _write_asset(
        runtime_paths.chat_files_dir,
        "Session-1",
        "turn-1",
        "alias.txt",
    )

    with pytest.raises(ChatAssetDeletionError, match="scope is ambiguous"):
        gc.delete_session_assets("session-1")

    assert exact.exists()
    assert alias.exists()


def test_chat_asset_gc_rejects_casefold_turn_alias_during_snapshot_scan(
    tmp_path: Path,
) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path)
    gc = ChatAssetGC(runtime_paths=runtime_paths)
    alias = _write_asset(
        runtime_paths.chat_files_dir,
        "session-1",
        "Turn-1",
        "alias.txt",
    )

    with pytest.raises(ChatAssetDeletionError, match="directory identity changed"):
        gc.list_snapshot_asset_references(
            session_id="session-1",
            turn_ids=["turn-1"],
            delete_entire_session=False,
        )

    assert alias.exists()


def test_chat_asset_gc_rejects_retargeted_root_for_delete_scan_and_clear(
    tmp_path: Path,
) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path / "runtime")
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "private.txt"
    outside_file.write_text("private", encoding="utf-8")
    runtime_paths.chat_files_dir.symlink_to(outside, target_is_directory=True)
    gc = ChatAssetGC(runtime_paths=runtime_paths)

    with pytest.raises(ChatAssetDeletionError, match="root was retargeted"):
        gc.delete_session_assets("session-1")
    with pytest.raises(ChatAssetDeletionError, match="root was retargeted"):
        gc.list_snapshot_asset_references(
            session_id="session-1",
            turn_ids=["turn-1"],
            delete_entire_session=False,
        )
    with pytest.raises(ChatAssetDeletionError, match="root was retargeted"):
        gc.clear_all_assets()

    assert outside_file.read_text(encoding="utf-8") == "private"


def test_runtime_paths_rejects_symlinked_runtime_base(
    tmp_path: Path,
) -> None:
    actual_runtime = tmp_path / "actual-runtime"
    actual_runtime.mkdir()
    linked_runtime = tmp_path / "linked-runtime"
    linked_runtime.symlink_to(actual_runtime, target_is_directory=True)

    with pytest.raises(RuntimeError, match="root must be a real directory"):
        RuntimePaths(base_dir=linked_runtime)


@pytest.mark.asyncio
async def test_chat_asset_gc_sweeps_orphans_after_grace_period(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path)
    now = 2_000_000.0
    gc = ChatAssetGC(runtime_paths=runtime_paths, now=lambda: now)
    active = _write_asset(runtime_paths.chat_files_dir, "active-session", "turn-1", "file.txt")
    old_orphan = _write_asset(runtime_paths.chat_files_dir, "old-orphan", "turn-1", "file.txt")
    recent_orphan = _write_asset(
        runtime_paths.chat_derived_dir, "recent-orphan", "turn-1", "file.txt"
    )
    old_timestamp = now - (48 * 3600)
    recent_timestamp = now - 60
    _touch_tree(old_orphan.parents[1], old_timestamp)
    _touch_tree(recent_orphan.parents[1], recent_timestamp)

    async with sqlite_connection_async(runtime_paths.chat_db_path) as db:
        await db.executescript(chat_initial.SCHEMA_SQL)
        await db.execute("""
            INSERT INTO chat_sessions (
                session_id, user_id, title, created_at_ms, updated_at_ms
            ) VALUES ('active-session', 'u1', 'Active', 1, 1)
            """)
        await db.commit()

    result = gc.sweep_orphan_assets(orphan_grace_hours=24)

    assert result["chat_asset_orphan_sessions_deleted"] == 1
    assert result["chat_asset_orphan_files_deleted"] == 1
    assert active.exists()
    assert not old_orphan.exists()
    assert recent_orphan.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("configured_grace_hours", "file_age_hours"),
    ((0, 24), (48, 26)),
)
async def test_chat_asset_gc_keeps_recent_unowned_file_in_active_session(
    tmp_path: Path,
    configured_grace_hours: int,
    file_age_hours: int,
) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path)
    now = 2_000_000.0
    unowned = _write_asset(
        runtime_paths.chat_files_dir,
        "active-session",
        "turn-1",
        "upload.txt",
    )
    timestamp = now - (file_age_hours * 3600)
    os.utime(unowned, (timestamp, timestamp))
    await _initialize_chat_asset_owners(
        runtime_paths,
        active_session_ids=("active-session",),
    )

    result = ChatAssetGC(
        runtime_paths=runtime_paths,
        now=lambda: now,
    ).sweep_orphan_assets(orphan_grace_hours=configured_grace_hours)

    assert result["chat_asset_orphan_files_deleted"] == 0
    assert unowned.exists()


@pytest.mark.asyncio
async def test_chat_asset_gc_deletes_old_unowned_file_in_active_session(
    tmp_path: Path,
) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path)
    now = 2_000_000.0
    unowned = _write_asset(
        runtime_paths.chat_files_dir,
        "active-session",
        "turn-1",
        "upload.txt",
    )
    os.utime(unowned, (now - (26 * 3600), now - (26 * 3600)))
    await _initialize_chat_asset_owners(
        runtime_paths,
        active_session_ids=("active-session",),
    )

    result = ChatAssetGC(
        runtime_paths=runtime_paths,
        now=lambda: now,
    ).sweep_orphan_assets(orphan_grace_hours=0)

    assert result["chat_asset_orphan_files_deleted"] == 1
    assert not unowned.exists()
    assert not unowned.parent.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("root_name", ("images", "files", "derived"))
async def test_chat_asset_gc_sweeps_unowned_files_from_each_active_asset_root(
    tmp_path: Path,
    root_name: str,
) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path)
    root_dir = {
        "images": runtime_paths.chat_images_dir,
        "files": runtime_paths.chat_files_dir,
        "derived": runtime_paths.chat_derived_dir,
    }[root_name]
    now = 2_000_000.0
    unowned = _write_asset(
        root_dir,
        "active-session",
        "turn-1",
        f"stale-{root_name}.txt",
    )
    os.utime(unowned, (now - (26 * 3600), now - (26 * 3600)))
    await _initialize_chat_asset_owners(
        runtime_paths,
        active_session_ids=("active-session",),
    )

    ChatAssetGC(
        runtime_paths=runtime_paths,
        now=lambda: now,
    ).sweep_orphan_assets(orphan_grace_hours=24)

    assert not unowned.exists()


@pytest.mark.asyncio
async def test_chat_asset_gc_preserves_hidden_owner_while_cleaning_same_turn_residue(
    tmp_path: Path,
) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path)
    now = 2_000_000.0
    ingestion = LocalChatAttachmentIngestionService(runtime_paths=runtime_paths)
    owned = Path(
        str(
            (
                await run_chat_asset_mutation(
                    ingestion.ingest_attachment,
                    session_id="active-session",
                    turn_id="turn-1",
                    original_name="accepted.txt",
                    content=b"accepted",
                    mime_type="text/plain",
                )
            )["storage_path"]
        )
    )
    unowned = Path(
        str(
            (
                await run_chat_asset_mutation(
                    ingestion.ingest_attachment,
                    session_id="active-session",
                    turn_id="turn-1",
                    original_name="interrupted.txt",
                    content=b"interrupted",
                    mime_type="text/plain",
                )
            )["storage_path"]
        )
    )
    old_timestamp = now - (26 * 3600)
    os.utime(owned, (old_timestamp, old_timestamp))
    os.utime(unowned, (old_timestamp, old_timestamp))
    await _initialize_chat_asset_owners(
        runtime_paths,
        active_session_ids=("active-session",),
        owners=(("hidden-message", owned, False),),
    )

    result = ChatAssetGC(
        runtime_paths=runtime_paths,
        now=lambda: now,
    ).sweep_orphan_assets(orphan_grace_hours=0)

    assert result["chat_asset_orphan_files_deleted"] == 1
    assert owned.exists()
    assert not unowned.exists()
    assert owned.parent.exists()


@pytest.mark.asyncio
async def test_chat_asset_gc_cleans_real_upload_that_never_gained_an_owner(
    tmp_path: Path,
) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path)
    now = 2_000_000.0
    await _initialize_chat_asset_owners(
        runtime_paths,
        active_session_ids=("active-session",),
    )
    attachment = await run_chat_asset_mutation(
        LocalChatAttachmentIngestionService(
            runtime_paths=runtime_paths,
        ).ingest_attachment,
        session_id="active-session",
        turn_id="turn-1",
        original_name="notes.md",
        content=b"# interrupted upload",
        mime_type="text/markdown",
    )
    upload_path = Path(str(attachment["storage_path"]))
    old_timestamp = now - (26 * 3600)
    os.utime(upload_path, (old_timestamp, old_timestamp))

    result = ChatAssetGC(
        runtime_paths=runtime_paths,
        now=lambda: now,
    ).sweep_orphan_assets(orphan_grace_hours=0)

    assert result["chat_asset_orphan_files_deleted"] == 1
    assert not upload_path.exists()


@pytest.mark.asyncio
async def test_chat_asset_gc_can_skip_orphan_sessions_without_skipping_active_residue(
    tmp_path: Path,
) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path)
    now = 2_000_000.0
    active_unowned = _write_asset(
        runtime_paths.chat_files_dir,
        "active-session",
        "turn-1",
        "interrupted.txt",
    )
    inactive_unowned = _write_asset(
        runtime_paths.chat_files_dir,
        "inactive-session",
        "turn-1",
        "retained.txt",
    )
    old_timestamp = now - (26 * 3600)
    os.utime(active_unowned, (old_timestamp, old_timestamp))
    _touch_tree(inactive_unowned.parents[1], old_timestamp)
    await _initialize_chat_asset_owners(
        runtime_paths,
        active_session_ids=("active-session",),
    )

    result = ChatAssetGC(
        runtime_paths=runtime_paths,
        now=lambda: now,
    ).sweep_orphan_assets(
        orphan_grace_hours=0,
        delete_orphan_sessions=False,
    )

    assert result["chat_asset_orphan_sessions_deleted"] == 0
    assert result["chat_asset_orphan_files_deleted"] == 1
    assert not active_unowned.exists()
    assert inactive_unowned.exists()


@pytest.mark.asyncio
async def test_chat_asset_gc_unlinks_old_file_symlink_without_following_it(
    tmp_path: Path,
) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path / "runtime")
    now = 2_000_000.0
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    link = (
        runtime_paths.chat_files_dir
        / "active-session"
        / "turn-1"
        / "interrupted.txt"
    )
    link.parent.mkdir(parents=True)
    link.symlink_to(outside)
    old_timestamp = now - (26 * 3600)
    os.utime(link, (old_timestamp, old_timestamp), follow_symlinks=False)
    await _initialize_chat_asset_owners(
        runtime_paths,
        active_session_ids=("active-session",),
    )

    ChatAssetGC(
        runtime_paths=runtime_paths,
        now=lambda: now,
    ).sweep_orphan_assets(orphan_grace_hours=0)

    assert not link.exists()
    assert not link.is_symlink()
    assert outside.read_text(encoding="utf-8") == "private"


@pytest.mark.asyncio
async def test_chat_asset_gc_preserves_case_variant_of_active_session(
    tmp_path: Path,
) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path)
    now = 2_000_000.0
    gc = ChatAssetGC(runtime_paths=runtime_paths, now=lambda: now)
    active = _write_asset(
        runtime_paths.chat_files_dir,
        "Active-Session",
        "turn-1",
        "file.txt",
    )
    _touch_tree(active.parents[1], now - (48 * 3600))

    async with sqlite_connection_async(runtime_paths.chat_db_path) as db:
        await db.executescript(chat_initial.SCHEMA_SQL)
        await db.execute("""
            INSERT INTO chat_sessions (
                session_id, user_id, title, created_at_ms, updated_at_ms
            ) VALUES ('active-session', 'u1', 'Active', 1, 1)
            """)
        await db.commit()

    result = gc.sweep_orphan_assets(orphan_grace_hours=0)

    assert result["chat_asset_orphan_sessions_deleted"] == 0
    assert result["chat_asset_orphan_files_deleted"] == 0
    assert active.exists()


def test_chat_asset_gc_fails_closed_when_chat_database_is_missing(
    tmp_path: Path,
) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path)
    now = 2_000_000.0
    old_asset = _write_asset(
        runtime_paths.chat_files_dir,
        "active-before-database-loss",
        "turn-1",
        "private.txt",
    )
    _touch_tree(old_asset.parents[1], now - (48 * 3600))

    result = ChatAssetGC(
        runtime_paths=runtime_paths,
        now=lambda: now,
    ).sweep_orphan_assets(orphan_grace_hours=0)

    assert result == {
        "chat_asset_orphan_sessions_deleted": 0,
        "chat_asset_orphan_files_deleted": 0,
        "chat_asset_orphan_dirs_deleted": 0,
    }
    assert old_asset.exists()


@pytest.mark.asyncio
async def test_chat_asset_gc_fails_closed_when_owner_migration_is_incomplete(
    tmp_path: Path,
) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path)
    now = 2_000_000.0
    old_asset = _write_asset(
        runtime_paths.chat_files_dir,
        "active-session",
        "turn-1",
        "private.txt",
    )
    os.utime(old_asset, (now - (48 * 3600), now - (48 * 3600)))
    async with sqlite_connection_async(runtime_paths.chat_db_path) as db:
        await db.executescript(chat_initial.SCHEMA_SQL)
        await db.execute("""
            INSERT INTO chat_sessions (
                session_id, user_id, title, created_at_ms, updated_at_ms
            ) VALUES ('active-session', 'u1', 'Active', 1, 1)
            """)
        await db.execute("DROP TABLE chat_message_asset_refs")
        await db.commit()

    result = ChatAssetGC(
        runtime_paths=runtime_paths,
        now=lambda: now,
    ).sweep_orphan_assets(orphan_grace_hours=0)

    assert result["chat_asset_orphan_files_deleted"] == 0
    assert old_asset.exists()


@pytest.mark.asyncio
async def test_chat_asset_gc_does_not_follow_orphan_session_symlink(
    tmp_path: Path,
) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path / "runtime")
    now = 2_000_000.0
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "fresh-private.txt"
    outside_file.write_text("private", encoding="utf-8")
    session_link = runtime_paths.chat_files_dir / "orphan-session"
    session_link.parent.mkdir(parents=True)
    session_link.symlink_to(outside, target_is_directory=True)
    os.utime(
        session_link,
        (now - (48 * 3600), now - (48 * 3600)),
        follow_symlinks=False,
    )
    async with sqlite_connection_async(runtime_paths.chat_db_path) as db:
        await db.executescript(chat_initial.SCHEMA_SQL)
        await db.commit()

    result = ChatAssetGC(
        runtime_paths=runtime_paths,
        now=lambda: now,
    ).sweep_orphan_assets(orphan_grace_hours=0)

    assert result["chat_asset_orphan_sessions_deleted"] == 0
    assert result["chat_asset_orphan_files_deleted"] == 1
    assert not session_link.is_symlink()
    assert outside_file.read_text(encoding="utf-8") == "private"


def test_chat_asset_gc_snapshot_scan_does_not_follow_directory_symlink(
    tmp_path: Path,
) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path / "runtime")
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "private.txt"
    outside_file.write_text("private", encoding="utf-8")
    directory_link = (
        runtime_paths.chat_files_dir
        / "session-1"
        / "turn-1"
        / "linked-directory"
    )
    directory_link.parent.mkdir(parents=True)
    directory_link.symlink_to(outside, target_is_directory=True)
    gc = ChatAssetGC(runtime_paths=runtime_paths)

    references = gc.list_snapshot_asset_references(
        session_id="session-1",
        turn_ids=["turn-1"],
        delete_entire_session=False,
    )

    assert references == [
        (
            "files/session-1/turn-1/linked-directory",
            "data/resources/chat/files/session-1/turn-1/linked-directory",
        )
    ]
    assert gc.delete_message_assets(references) == 1
    assert outside_file.read_text(encoding="utf-8") == "private"


@pytest.mark.asyncio
async def test_chat_asset_gc_rechecks_turn_directory_before_unlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path / "runtime")
    now = 2_000_000.0
    inside_asset = _write_asset(
        runtime_paths.chat_files_dir,
        "active-session",
        "turn-1",
        "private.txt",
    )
    os.utime(inside_asset, (now - (48 * 3600), now - (48 * 3600)))
    outside_turn = tmp_path / "outside-turn"
    outside_turn.mkdir()
    outside_asset = outside_turn / inside_asset.name
    outside_asset.write_text("outside", encoding="utf-8")
    await _initialize_chat_asset_owners(
        runtime_paths,
        active_session_ids=("active-session",),
    )
    gc = ChatAssetGC(runtime_paths=runtime_paths, now=lambda: now)
    original_turn_dir = inside_asset.parent
    parked_turn_dir = original_turn_dir.with_name("parked-turn")
    replaced = False

    def replace_turn_before_unlink(_path: Path, _cutoff: float) -> bool:
        nonlocal replaced
        original_turn_dir.rename(parked_turn_dir)
        original_turn_dir.symlink_to(outside_turn, target_is_directory=True)
        replaced = True
        return True

    monkeypatch.setattr(
        gc,
        "_is_file_older_than",
        replace_turn_before_unlink,
    )

    result = gc.sweep_orphan_assets(
        orphan_grace_hours=0,
        delete_orphan_sessions=False,
    )

    assert replaced is True
    assert result["chat_asset_orphan_files_deleted"] == 0
    assert (parked_turn_dir / inside_asset.name).read_text(encoding="utf-8") == "asset"
    assert outside_asset.read_text(encoding="utf-8") == "outside"


@pytest.mark.asyncio
async def test_chat_asset_gc_counts_one_orphan_session_across_all_roots(
    tmp_path: Path,
) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path)
    now = 2_000_000.0
    for root_dir in (
        runtime_paths.chat_images_dir,
        runtime_paths.chat_files_dir,
        runtime_paths.chat_derived_dir,
    ):
        asset = _write_asset(
            root_dir,
            "same-orphan-session",
            "turn-1",
            "asset.txt",
        )
        _touch_tree(asset.parents[1], now - (48 * 3600))
    async with sqlite_connection_async(runtime_paths.chat_db_path) as db:
        await db.executescript(chat_initial.SCHEMA_SQL)
        await db.commit()

    result = ChatAssetGC(
        runtime_paths=runtime_paths,
        now=lambda: now,
    ).sweep_orphan_assets(orphan_grace_hours=0)

    assert result["chat_asset_orphan_sessions_deleted"] == 1
    assert result["chat_asset_orphan_files_deleted"] == 3


@pytest.mark.asyncio
async def test_chat_asset_gc_does_not_preserve_tombstoned_message_scope(
    tmp_path: Path,
) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path)
    now = 2_000_000.0
    old_asset = _write_asset(
        runtime_paths.chat_files_dir,
        "deleted-session",
        "turn-1",
        "private.txt",
    )
    _touch_tree(old_asset.parents[1], now - (48 * 3600))
    asset_key = old_asset.relative_to(
        runtime_paths.chat_resources_dir,
    ).as_posix()
    storage_rel_path = old_asset.relative_to(runtime_paths.base_dir).as_posix()
    async with sqlite_connection_async(runtime_paths.chat_db_path) as db:
        await db.executescript(chat_initial.SCHEMA_SQL)
        await db.execute("""
            INSERT INTO chat_sessions (
                session_id, user_id, title, created_at_ms, updated_at_ms
            ) VALUES ('deleted-session', 'u1', '', 1, 1)
            """)
        await db.execute("""
            INSERT INTO chat_messages (
                message_id, session_id, turn_id, user_id, role,
                message_kind, content_text, payload_json, is_final,
                is_visible, created_at_ms, sequence_no
            ) VALUES (
                'stale-message', 'deleted-session', 'turn-1', 'u1', 'user',
                'user_text', '', '{}', 1, 0, 1, 1
            )
            """)
        await db.execute(
            """
            INSERT INTO chat_message_asset_refs (
                message_id, asset_key, storage_rel_path, asset_kind,
                created_at_ms
            ) VALUES ('stale-message', ?, ?, 'attachment', 1)
            """,
            (asset_key, storage_rel_path),
        )
        await db.execute("""
            UPDATE chat_sessions
            SET deleted_at_ms = 2, updated_at_ms = 2
            WHERE session_id = 'deleted-session'
            """)
        await db.commit()

    result = ChatAssetGC(
        runtime_paths=runtime_paths,
        now=lambda: now,
    ).sweep_orphan_assets(orphan_grace_hours=0)

    assert result["chat_asset_orphan_sessions_deleted"] == 1
    assert not old_asset.exists()


@pytest.mark.asyncio
async def test_chat_asset_gc_enumerates_only_existing_active_scopes_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path)
    now = 2_000_000.0
    existing_asset = _write_asset(
        runtime_paths.chat_files_dir,
        "session-0000",
        "turn-1",
        "recent.txt",
    )
    os.utime(existing_asset, (now - 60, now - 60))
    await _initialize_chat_asset_owners(
        runtime_paths,
        active_session_ids=tuple(
            f"session-{index:04d}" for index in range(1_000)
        ),
    )

    original_iterdir = Path.iterdir
    monitored = {
        runtime_paths.chat_files_dir,
        existing_asset.parents[1],
        existing_asset.parent,
    }
    enumeration_counts = {path: 0 for path in monitored}

    def counting_iterdir(path: Path):
        if path in enumeration_counts:
            enumeration_counts[path] += 1
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", counting_iterdir)

    result = ChatAssetGC(
        runtime_paths=runtime_paths,
        now=lambda: now,
    ).sweep_orphan_assets(
        orphan_grace_hours=0,
        delete_orphan_sessions=False,
    )

    assert result["chat_asset_orphan_files_deleted"] == 0
    assert enumeration_counts == {
        runtime_paths.chat_files_dir: 1,
        existing_asset.parents[1]: 1,
        existing_asset.parent: 1,
    }
    assert existing_asset.exists()
