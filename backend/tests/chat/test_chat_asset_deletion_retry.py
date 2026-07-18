from __future__ import annotations

import json
from pathlib import Path

import pytest

from _shared.db_schema import apply_chain_schema
from magi.chat.asset_gc import ChatAssetDeletionError, ChatAssetGC
from magi.chat.read_service import ChatReadService
from magi.utils.runtime import RuntimePaths


def _build_service(tmp_path: Path) -> tuple[ChatReadService, RuntimePaths]:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    apply_chain_schema("chat", runtime_paths.chat_db_path)
    service = object.__new__(ChatReadService)
    service._runtime_paths = runtime_paths
    service._chat_db_path = runtime_paths.chat_db_path
    service._l1_db_path = runtime_paths.l1_memory_db_path
    service._runtime_trace_db_path = runtime_paths.runtime_trace_db_path
    service._asset_gc = ChatAssetGC(runtime_paths=runtime_paths)
    service._conn = None
    return service, runtime_paths


def _seed_chat(
    service: ChatReadService,
    runtime_paths: RuntimePaths,
    *,
    session_id: str,
    message_id: str,
) -> Path:
    turn_id = f"turn-{session_id}"
    attachment_id = f"attachment-{session_id}"
    asset_path = runtime_paths.chat_files_dir / session_id / turn_id / f"{attachment_id}.txt"
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    asset_path.write_text("private attachment", encoding="utf-8")
    storage_rel_path = asset_path.relative_to(runtime_paths.base_dir).as_posix()
    payload_json = json.dumps(
        {
            "attachments": [
                {
                    "attachment_id": attachment_id,
                    "storage_path": storage_rel_path,
                }
            ]
        }
    )

    conn = service._get_conn()
    conn.execute(
        """
        INSERT INTO chat_sessions(
            session_id, user_id, title, created_at_ms, updated_at_ms,
            message_count
        ) VALUES (?, 'u1', 'Private chat', 1, 1, 1)
        """,
        (session_id,),
    )
    conn.execute(
        """
        INSERT INTO chat_turns(
            turn_id, session_id, user_id, status, response_mode,
            ux_plan_json, created_at_ms, updated_at_ms
        ) VALUES (?, ?, 'u1', 'completed', 'final_only', '{}', 1, 1)
        """,
        (turn_id, session_id),
    )
    conn.execute(
        """
        INSERT INTO chat_messages(
            message_id, session_id, turn_id, user_id, role, message_kind,
            content_text, payload_json, is_final, is_visible,
            created_at_ms, sequence_no
        ) VALUES (?, ?, ?, 'u1', 'user', 'user_text',
                  'private message', ?, 1, 1, 1, 1)
        """,
        (message_id, session_id, turn_id, payload_json),
    )
    conn.execute(
        """
        INSERT INTO chat_attachments(
            attachment_id, session_id, turn_id, message_id, user_id,
            kind, original_name, mime_type, size_bytes,
            storage_rel_path, created_at_ms
        ) VALUES (?, ?, ?, ?, 'u1', 'file', 'private.txt',
                  'text/plain', 18, ?, 1)
        """,
        (attachment_id, session_id, turn_id, message_id, storage_rel_path),
    )
    conn.commit()
    return asset_path


def _seed_new_chat_after_snapshot(
    service: ChatReadService,
    runtime_paths: RuntimePaths,
    *,
    session_id: str,
) -> Path:
    turn_id = f"turn-new-{session_id}"
    message_id = f"message-new-{session_id}"
    attachment_id = f"attachment-new-{session_id}"
    asset_path = runtime_paths.chat_files_dir / session_id / turn_id / f"{attachment_id}.txt"
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    asset_path.write_text("new attachment", encoding="utf-8")
    storage_rel_path = asset_path.relative_to(runtime_paths.base_dir).as_posix()

    conn = service._get_conn()
    conn.execute(
        """
        INSERT INTO chat_turns(
            turn_id, session_id, user_id, status, response_mode,
            ux_plan_json, created_at_ms, updated_at_ms
        ) VALUES (?, ?, 'u1', 'completed', 'final_only', '{}', 2, 2)
        """,
        (turn_id, session_id),
    )
    conn.execute(
        """
        INSERT INTO chat_messages(
            message_id, session_id, turn_id, user_id, role, message_kind,
            content_text, payload_json, is_final, is_visible,
            created_at_ms, sequence_no
        ) VALUES (?, ?, ?, 'u1', 'user', 'user_text',
                  'new private message', '{}', 1, 1, 2, 2)
        """,
        (message_id, session_id, turn_id),
    )
    conn.execute(
        """
        INSERT INTO chat_attachments(
            attachment_id, session_id, turn_id, message_id, user_id,
            kind, original_name, mime_type, size_bytes,
            storage_rel_path, created_at_ms
        ) VALUES (?, ?, ?, ?, 'u1', 'file', 'new-private.txt',
                  'text/plain', 14, ?, 2)
        """,
        (attachment_id, session_id, turn_id, message_id, storage_rel_path),
    )
    conn.execute(
        """
        UPDATE chat_sessions
        SET last_message_at_ms = 2,
            last_user_message_at_ms = 2,
            last_message_preview = 'new private message',
            last_user_message_preview = 'new private message',
            message_count = 2
        WHERE session_id = ?
        """,
        (session_id,),
    )
    conn.commit()
    return asset_path


def _fail_once(monkeypatch: pytest.MonkeyPatch, target: object, method_name: str) -> None:
    original = getattr(target, method_name)
    attempts = 0

    def flaky(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ChatAssetDeletionError("simulated managed asset delete failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(target, method_name, flaky)


def test_session_delete_failure_keeps_chat_rows_for_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    asset_path = _seed_chat(
        service,
        runtime_paths,
        session_id="session-delete",
        message_id="message-delete",
    )
    _fail_once(monkeypatch, service._asset_gc, "delete_session_assets")

    with pytest.raises(ChatAssetDeletionError):
        service.delete_session("u1", "session-delete")

    conn = service._get_conn()
    assert asset_path.exists()
    assert (
        conn.execute(
            "SELECT deleted_at_ms FROM chat_sessions WHERE session_id = 'session-delete'"
        ).fetchone()[0]
        is None
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM chat_attachments WHERE session_id = 'session-delete'"
        ).fetchone()[0]
        == 1
    )

    service.delete_session("u1", "session-delete")

    assert not asset_path.exists()
    assert (
        conn.execute(
            "SELECT deleted_at_ms FROM chat_sessions WHERE session_id = 'session-delete'"
        ).fetchone()[0]
        is not None
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM chat_attachments WHERE session_id = 'session-delete'"
        ).fetchone()[0]
        == 0
    )
    service.close()


def test_history_clear_failure_keeps_attachment_metadata_for_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    asset_path = _seed_chat(
        service,
        runtime_paths,
        session_id="session-clear",
        message_id="message-clear",
    )
    _fail_once(monkeypatch, service._asset_gc, "delete_session_assets")

    with pytest.raises(ChatAssetDeletionError):
        service.clear_conversation_history("u1", "session-clear")

    conn = service._get_conn()
    assert asset_path.exists()
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM chat_messages WHERE session_id = 'session-clear'"
        ).fetchone()[0]
        == 1
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM chat_attachments WHERE session_id = 'session-clear'"
        ).fetchone()[0]
        == 1
    )

    service.clear_conversation_history("u1", "session-clear")

    assert not asset_path.exists()
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM chat_messages WHERE session_id = 'session-clear'"
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM chat_attachments WHERE session_id = 'session-clear'"
        ).fetchone()[0]
        == 0
    )
    service.close()


def test_history_snapshot_recovery_physically_removes_only_the_old_transcript(
    tmp_path: Path,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    old_asset_path = _seed_chat(
        service,
        runtime_paths,
        session_id="session-recovery",
        message_id="message-recovery",
    )
    old_turn_id = "turn-session-recovery"
    orphan_old_asset = (
        runtime_paths.chat_derived_dir / "session-recovery" / old_turn_id / "orphan-private.txt"
    )
    orphan_old_asset.parent.mkdir(parents=True, exist_ok=True)
    orphan_old_asset.write_text("old derived content", encoding="utf-8")
    new_asset_path = _seed_new_chat_after_snapshot(
        service,
        runtime_paths,
        session_id="session-recovery",
    )

    service.clear_conversation_history_snapshot(
        "u1",
        "session-recovery",
        ["message-recovery"],
        [old_turn_id],
    )

    conn = service._get_conn()
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM chat_messages WHERE message_id = 'message-recovery'"
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM chat_turns WHERE turn_id = ?",
            (old_turn_id,),
        ).fetchone()[0]
        == 0
    )
    assert tuple(conn.execute("""
            SELECT content_text, is_visible
            FROM chat_messages
            WHERE message_id = 'message-new-session-recovery'
            """).fetchone()) == ("new private message", 1)
    assert not old_asset_path.exists()
    assert not orphan_old_asset.exists()
    assert new_asset_path.exists()

    history_version = conn.execute(
        "SELECT history_version FROM chat_sessions WHERE session_id = 'session-recovery'"
    ).fetchone()[0]
    service.clear_conversation_history_snapshot(
        "u1",
        "session-recovery",
        ["message-recovery"],
        [old_turn_id],
    )
    assert (
        conn.execute(
            "SELECT history_version FROM chat_sessions WHERE session_id = 'session-recovery'"
        ).fetchone()[0]
        == history_version
    )
    service.close()


def test_history_snapshot_asset_failure_keeps_old_rows_for_recovery_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    old_asset_path = _seed_chat(
        service,
        runtime_paths,
        session_id="session-snapshot-retry",
        message_id="message-snapshot-retry",
    )
    new_asset_path = _seed_new_chat_after_snapshot(
        service,
        runtime_paths,
        session_id="session-snapshot-retry",
    )
    _fail_once(
        monkeypatch,
        service._asset_gc,
        "delete_history_snapshot_assets",
    )

    with pytest.raises(ChatAssetDeletionError):
        service.clear_conversation_history_snapshot(
            "u1",
            "session-snapshot-retry",
            ["message-snapshot-retry"],
            ["turn-session-snapshot-retry"],
        )

    conn = service._get_conn()
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM chat_messages WHERE message_id = 'message-snapshot-retry'"
        ).fetchone()[0]
        == 1
    )
    assert old_asset_path.exists()
    assert new_asset_path.exists()

    service.clear_conversation_history_snapshot(
        "u1",
        "session-snapshot-retry",
        ["message-snapshot-retry"],
        ["turn-session-snapshot-retry"],
    )

    assert (
        conn.execute(
            "SELECT COUNT(*) FROM chat_messages WHERE message_id = 'message-snapshot-retry'"
        ).fetchone()[0]
        == 0
    )
    assert not old_asset_path.exists()
    assert new_asset_path.exists()
    service.close()


def test_message_delete_failure_keeps_exact_paths_for_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    asset_path = _seed_chat(
        service,
        runtime_paths,
        session_id="session-message",
        message_id="message-exact",
    )
    _fail_once(monkeypatch, service._asset_gc, "delete_message_assets")

    with pytest.raises(ChatAssetDeletionError):
        service.forget_message_artifacts("u1", "session-message", "message-exact")

    conn = service._get_conn()
    row = conn.execute(
        "SELECT content_text, payload_json, is_visible "
        "FROM chat_messages WHERE message_id = 'message-exact'"
    ).fetchone()
    assert asset_path.exists()
    assert row["content_text"] == "private message"
    assert row["is_visible"] == 1
    assert json.loads(row["payload_json"])["attachments"]
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM chat_attachments WHERE message_id = 'message-exact'"
        ).fetchone()[0]
        == 1
    )

    assert service.forget_message_artifacts("u1", "session-message", "message-exact")

    assert not asset_path.exists()
    row = conn.execute(
        "SELECT content_text, payload_json, is_visible "
        "FROM chat_messages WHERE message_id = 'message-exact'"
    ).fetchone()
    assert tuple(row) == ("", "{}", 0)
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM chat_attachments WHERE message_id = 'message-exact'"
        ).fetchone()[0]
        == 0
    )
    service.close()


def test_explicit_delete_is_strict_but_orphan_sweep_is_best_effort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    asset_path = runtime_paths.chat_files_dir / "orphan-session" / "turn-1" / "private.txt"
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    asset_path.write_text("private", encoding="utf-8")
    gc = ChatAssetGC(runtime_paths=runtime_paths, now=lambda: 10**12)

    def fail_delete(_path: Path) -> None:
        raise PermissionError("simulated filesystem denial")

    monkeypatch.setattr("magi.chat.asset_gc.shutil.rmtree", fail_delete)

    with pytest.raises(ChatAssetDeletionError):
        gc.delete_session_assets("orphan-session")

    result = gc.sweep_orphan_session_assets(orphan_grace_hours=0)

    assert result["chat_asset_orphan_sessions_deleted"] == 0
    assert result["chat_asset_orphan_files_deleted"] == 0
    assert asset_path.exists()
