"""Workspace discovery coverage for memory context options."""

from __future__ import annotations

import shutil
import sqlite3

import pytest

from magi.bootstrap.context import RuntimeBootstrapContext
from magi.chat import workspace_identity
from magi.chat.lifecycle import ChatStoreModule
from magi.chat.read import session_operations
from magi.chat.read_service import ChatReadService
from magi.core.workspace import WorkspaceStateStore
from magi.memory.context_scope import (
    ContextCatalog,
    ContextResolutionSignals,
    ContextScopeResolver,
    context_id_for_workspace,
)


def test_workspace_path_listing_is_complete_and_keeps_archived_sessions(
    tmp_path,
    runtime_paths_with_schema,
) -> None:
    service = ChatReadService()
    service._chat_db_path = runtime_paths_with_schema.chat_db_path
    expected_paths = [str(tmp_path / f"workspace-{index:03d}") for index in range(205)]
    archived_path = str(tmp_path / "archived-workspace")
    deleted_path = str(tmp_path / "deleted-workspace")
    other_user_path = str(tmp_path / "other-user-workspace")
    try:
        for index, workspace_path in enumerate(expected_paths):
            service.create_new_session(
                "local_user",
                workspace_path,
                idempotency_key=f"workspace-session-{index:03d}",
            )
        archived_session_id = service.create_new_session(
            "local_user",
            archived_path,
            idempotency_key="archived-session",
        )
        deleted_session_id = service.create_new_session(
            "local_user",
            deleted_path,
            idempotency_key="deleted-session",
        )
        service.create_new_session(
            "other_user",
            other_user_path,
            idempotency_key="other-user-session",
        )
        with sqlite3.connect(runtime_paths_with_schema.chat_db_path) as connection:
            connection.execute(
                "UPDATE chat_sessions SET archived_at_ms = 1 WHERE session_id = ?",
                (archived_session_id,),
            )
            connection.execute(
                "UPDATE chat_sessions SET deleted_at_ms = 1 WHERE session_id = ?",
                (deleted_session_id,),
            )
            connection.commit()

        workspace_paths = service.list_workspace_paths("local_user")

        assert len(workspace_paths) == 206
        assert set(expected_paths).issubset(workspace_paths)
        assert archived_path in workspace_paths
        assert deleted_path not in workspace_paths
        assert other_user_path not in workspace_paths
    finally:
        service.close()


def test_session_claim_keeps_a_copied_workspace_isolated_after_source_deletion(
    tmp_path,
    runtime_paths_with_schema,
) -> None:
    service = ChatReadService()
    service._chat_db_path = runtime_paths_with_schema.chat_db_path
    original = tmp_path / "original"
    original.mkdir()
    copied = tmp_path / "copied"
    try:
        service.create_new_session(
            "local_user",
            str(original),
            idempotency_key="original-session",
        )
        original_context_id = context_id_for_workspace(str(original))
        shutil.copytree(original, copied)
        temporary_copied_context_id = context_id_for_workspace(str(copied))
        assert temporary_copied_context_id != original_context_id

        service.create_new_session(
            "local_user",
            str(copied),
            idempotency_key="copied-session",
        )
        copied_context_id = context_id_for_workspace(str(copied))
        assert copied_context_id != temporary_copied_context_id
        assert copied_context_id != original_context_id
        shutil.rmtree(original)

        assert context_id_for_workspace(str(copied)) == copied_context_id
        assert context_id_for_workspace(str(copied)) != original_context_id
    finally:
        service.close()


def test_session_workspace_switch_after_source_deletion_gets_a_new_identity(
    tmp_path,
    runtime_paths_with_schema,
) -> None:
    service = ChatReadService()
    service._chat_db_path = runtime_paths_with_schema.chat_db_path
    original = tmp_path / "original"
    original.mkdir()
    moved = tmp_path / "moved"
    try:
        session_id = service.create_new_session(
            "local_user",
            str(original),
            idempotency_key="move-session",
        )
        original_context_id = context_id_for_workspace(str(original))
        shutil.move(str(original), str(moved))

        temporary_moved_context_id = context_id_for_workspace(str(moved))
        assert temporary_moved_context_id != original_context_id
        service.update_session_workspace("local_user", session_id, str(moved))
        moved_context_id = context_id_for_workspace(str(moved))
        original.mkdir()
        service.create_new_session(
            "local_user",
            str(original),
            idempotency_key="new-project-at-old-path",
        )

        restored_path_context_id = context_id_for_workspace(str(original))
        assert moved_context_id != temporary_moved_context_id
        assert moved_context_id != original_context_id
        assert restored_path_context_id != original_context_id
        assert restored_path_context_id != moved_context_id
    finally:
        service.close()


def test_session_workspace_switch_does_not_reuse_a_live_project_identity(
    tmp_path,
    runtime_paths_with_schema,
) -> None:
    service = ChatReadService()
    service._chat_db_path = runtime_paths_with_schema.chat_db_path
    original = tmp_path / "original"
    original.mkdir()
    switched = tmp_path / "switched"
    try:
        session_id = service.create_new_session(
            "local_user",
            str(original),
            idempotency_key="switch-session",
        )
        original_context_id = context_id_for_workspace(str(original))
        shutil.copytree(original, switched)

        service.update_session_workspace("local_user", session_id, str(switched))

        assert context_id_for_workspace(str(switched)) != original_context_id
        assert context_id_for_workspace(str(original)) == original_context_id
    finally:
        service.close()


def test_workspace_claim_failure_does_not_block_session_creation(
    tmp_path,
    runtime_paths_with_schema,
    monkeypatch,
) -> None:
    service = ChatReadService()
    service._chat_db_path = runtime_paths_with_schema.chat_db_path
    workspace = tmp_path / "read-only-workspace"
    workspace.mkdir()

    def _fail_claim(*_args, **_kwargs):
        raise OSError("workspace is read-only")

    warnings = []
    monkeypatch.setattr(
        WorkspaceStateStore,
        "claim_identity",
        _fail_claim,
    )
    monkeypatch.setattr(
        workspace_identity.logger,
        "warning",
        lambda event, **fields: warnings.append((event, fields)),
    )
    try:
        session_id = service.create_new_session(
            "local_user",
            str(workspace),
            idempotency_key="claim-failure-session",
        )

        assert service.get_session_summary("local_user", session_id) is not None
        assert warnings == [
            (
                "Failed to claim workspace identity",
                {"error_type": "OSError"},
            )
        ]
        assert str(workspace) not in str(warnings)
    finally:
        service.close()


@pytest.mark.asyncio
async def test_failed_claim_stays_global_until_a_successful_retry(
    tmp_path,
    runtime_paths_with_schema,
    monkeypatch,
) -> None:
    service = ChatReadService()
    service._chat_db_path = runtime_paths_with_schema.chat_db_path
    workspace = tmp_path / "temporarily-read-only"
    workspace.mkdir()
    original_claim = WorkspaceStateStore.claim_identity

    def _fail_claim(*_args, **_kwargs):
        raise OSError("workspace is read-only")

    monkeypatch.setattr(WorkspaceStateStore, "claim_identity", _fail_claim)
    try:
        session_id = service.create_new_session(
            "local_user",
            str(workspace),
            idempotency_key="temporary-claim-failure",
        )
        catalog = ContextCatalog(str(runtime_paths_with_schema.memory_db_path))
        paths = service.list_workspace_paths("local_user")

        assert await catalog.sync_workspace_project_options(paths) == []
        assert (
            await ContextScopeResolver(str(runtime_paths_with_schema.memory_db_path)).resolve(
                ContextResolutionSignals(workspace_path=str(workspace))
            )
            == {}
        )

        monkeypatch.setattr(WorkspaceStateStore, "claim_identity", original_claim)
        service.update_session_workspace("local_user", session_id, str(workspace))
        options = await catalog.sync_workspace_project_options(paths)
        first_scope = await ContextScopeResolver(
            str(runtime_paths_with_schema.memory_db_path)
        ).resolve(ContextResolutionSignals(workspace_path=str(workspace)))
        service.update_session_workspace("local_user", session_id, str(workspace))
        second_scope = await ContextScopeResolver(
            str(runtime_paths_with_schema.memory_db_path)
        ).resolve(ContextResolutionSignals(workspace_path=str(workspace)))

        assert len(options) == 1
        assert (
            first_scope
            == second_scope
            == {
                "all_of": [
                    {
                        "dimension": "project",
                        "context_id": options[0].context_id,
                    }
                ]
            }
        )
    finally:
        service.close()


def test_idempotent_session_retry_does_not_claim_a_different_workspace(
    tmp_path,
    runtime_paths_with_schema,
) -> None:
    service = ChatReadService()
    service._chat_db_path = runtime_paths_with_schema.chat_db_path
    original = tmp_path / "original-workspace"
    unexpected = tmp_path / "unexpected-workspace"
    original.mkdir()
    unexpected.mkdir()
    try:
        session_id = service.create_new_session(
            "local_user",
            str(original),
            idempotency_key="idempotent-session",
        )
        retried_id = service.create_new_session(
            "local_user",
            str(unexpected),
            idempotency_key="idempotent-session",
        )

        assert retried_id == session_id
        assert (original / ".magi" / "local" / "workspace-state.json").is_file()
        assert not (unexpected / ".magi").exists()
        summary = service.get_session_summary("local_user", session_id)
        assert summary is not None
        assert summary.workspace_path == str(original)
    finally:
        service.close()


@pytest.mark.asyncio
async def test_user_turn_persists_and_claims_workspace_without_retry_side_effects(
    tmp_path,
    runtime_paths_with_schema,
) -> None:
    from magi.chat.store import ChatStore, ChatTurnConflictError

    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    workspace = tmp_path / "send-workspace"
    retry_workspace = tmp_path / "retry-workspace"
    conflict_workspace = tmp_path / "conflict-workspace"
    workspace.mkdir()
    retry_workspace.mkdir()
    conflict_workspace.mkdir()
    temporary_context_id = context_id_for_workspace(str(workspace))
    try:
        created = await store.create_user_turn_once(
            session_id="send-session",
            user_id="local_user",
            turn_id="send-turn",
            message_text="hello",
            created_at_ms=100,
            runtime_envelope={"workspace_path": str(workspace)},
            request_fingerprint="accepted-request",
        )
        retried = await store.create_user_turn_once(
            session_id="send-session",
            user_id="local_user",
            turn_id="send-turn",
            message_text="hello",
            created_at_ms=200,
            runtime_envelope={"workspace_path": str(retry_workspace)},
            request_fingerprint="accepted-request",
        )
        with pytest.raises(ChatTurnConflictError):
            await store.create_user_turn_once(
                session_id="send-session",
                user_id="local_user",
                turn_id="send-turn",
                message_text="hello",
                created_at_ms=300,
                runtime_envelope={"workspace_path": str(conflict_workspace)},
                request_fingerprint="conflicting-request",
            )

        with sqlite3.connect(runtime_paths_with_schema.chat_db_path) as connection:
            persisted_path = connection.execute(
                "SELECT workspace_path FROM chat_sessions WHERE session_id = ?",
                ("send-session",),
            ).fetchone()
        assert created.created is True
        assert retried.created is False
        assert persisted_path == (str(workspace),)
        assert context_id_for_workspace(str(workspace)) != temporary_context_id
        assert not (retry_workspace / ".magi").exists()
        assert not (conflict_workspace / ".magi").exists()
    finally:
        await store.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_column", [None, "archived_at_ms", "deleted_at_ms"])
async def test_user_turn_cannot_take_over_or_revive_an_existing_session(
    tmp_path,
    runtime_paths_with_schema,
    terminal_column,
) -> None:
    from magi.chat.store import ChatStore, ChatTurnConflictError

    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    original = tmp_path / "owned-workspace"
    unexpected = tmp_path / "unexpected-workspace"
    original.mkdir()
    unexpected.mkdir()
    try:
        await store.create_user_turn_once(
            session_id="owned-session",
            user_id="owner",
            turn_id="owned-turn",
            message_text="first",
            created_at_ms=100,
            runtime_envelope={"workspace_path": str(original)},
            request_fingerprint="owned-request",
        )
        if terminal_column is not None:
            with sqlite3.connect(runtime_paths_with_schema.chat_db_path) as connection:
                connection.execute(
                    f"UPDATE chat_sessions SET {terminal_column} = 123 "
                    "WHERE session_id = 'owned-session'"
                )
                connection.commit()

        with pytest.raises(ChatTurnConflictError):
            await store.create_user_turn_once(
                session_id="owned-session",
                user_id="intruder" if terminal_column is None else "owner",
                turn_id="rejected-turn",
                message_text="second",
                created_at_ms=200,
                runtime_envelope={"workspace_path": str(unexpected)},
                request_fingerprint="rejected-request",
            )

        with sqlite3.connect(runtime_paths_with_schema.chat_db_path) as connection:
            session = connection.execute(
                """
                SELECT user_id, workspace_path, message_count
                FROM chat_sessions WHERE session_id = 'owned-session'
                """
            ).fetchone()
            rejected_turn_count = connection.execute(
                "SELECT COUNT(*) FROM chat_turns WHERE turn_id = 'rejected-turn'"
            ).fetchone()
        assert session == ("owner", str(original), 1)
        assert rejected_turn_count == (0,)
        assert not (unexpected / ".magi").exists()
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_user_turn_workspace_update_does_not_infer_a_move(
    tmp_path,
    runtime_paths_with_schema,
) -> None:
    from magi.chat.store import ChatStore

    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    original = tmp_path / "send-original"
    moved = tmp_path / "send-moved"
    original.mkdir()
    try:
        await store.create_user_turn_once(
            session_id="moving-send-session",
            user_id="local_user",
            turn_id="moving-send-turn-1",
            message_text="before move",
            created_at_ms=100,
            runtime_envelope={"workspace_path": str(original)},
            request_fingerprint="moving-send-1",
        )
        original_context_id = context_id_for_workspace(str(original))
        shutil.move(str(original), str(moved))

        await store.create_user_turn_once(
            session_id="moving-send-session",
            user_id="local_user",
            turn_id="moving-send-turn-2",
            message_text="after move",
            created_at_ms=200,
            runtime_envelope={"workspace_path": str(moved)},
            request_fingerprint="moving-send-2",
        )

        assert context_id_for_workspace(str(moved)) != original_context_id
        with sqlite3.connect(runtime_paths_with_schema.chat_db_path) as connection:
            assert connection.execute(
                "SELECT workspace_path FROM chat_sessions WHERE session_id = ?",
                ("moving-send-session",),
            ).fetchone() == (str(moved),)
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_chat_bootstrap_claims_existing_session_workspaces(
    tmp_path,
    runtime_paths_with_schema,
    monkeypatch,
) -> None:
    service = ChatReadService()
    service._chat_db_path = runtime_paths_with_schema.chat_db_path
    original = tmp_path / "legacy-original"
    original.mkdir()
    copied = tmp_path / "legacy-copy"
    service.create_new_session(
        "local_user",
        str(original),
        idempotency_key="legacy-original-session",
    )
    shutil.copytree(original, copied)
    temporary_copied_context_id = context_id_for_workspace(str(copied))
    original_claim = session_operations.claim_workspace_identity
    monkeypatch.setattr(
        session_operations,
        "claim_workspace_identity",
        lambda _workspace_path: False,
    )
    service.create_new_session(
        "local_user",
        str(copied),
        idempotency_key="legacy-copy-session",
    )
    service.close()
    monkeypatch.setattr(
        session_operations,
        "claim_workspace_identity",
        original_claim,
    )
    context = RuntimeBootstrapContext()
    context.core.runtime_paths = runtime_paths_with_schema
    module = ChatStoreModule(context)
    try:
        await module.init()
        copied_context_id = context_id_for_workspace(str(copied))
        assert copied_context_id != temporary_copied_context_id
        first_claim_content = (copied / ".magi" / "local" / "workspace-state.json").read_text(
            encoding="utf-8"
        )
    finally:
        await module.shutdown()

    second_module = ChatStoreModule(context)
    try:
        await second_module.init()
        second_claim_content = (copied / ".magi" / "local" / "workspace-state.json").read_text(
            encoding="utf-8"
        )
        shutil.rmtree(original)

        assert second_claim_content == first_claim_content
        assert context_id_for_workspace(str(copied)) == copied_context_id
    finally:
        await second_module.shutdown()
