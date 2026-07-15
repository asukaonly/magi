from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest
from fastapi.responses import FileResponse
from pydantic import ValidationError

from magi.api.routers import messages as messages_router
from magi.api.routers import (
    messages_content,
    messages_dispatch,
    messages_mutations,
    messages_run_control,
    messages_sessions,
)
from magi.chat.read_service import ChatDisplayMessage
from magi.api.services.message_dispatch_service import MessageDispatchOutcome
from magi.i18n import language_context


async def _runtime_ready(_app):  # type: ignore[no-untyped-def]
    return {
        "runtime_ready": True,
        "runtime_status": "ready",
        "startup_state": "ready",
        "deferred_reason": None,
    }


@pytest.mark.asyncio
async def test_send_user_message_uses_runtime_namespace_for_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def _fake_dispatch_user_message(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return MessageDispatchOutcome(
            success=True,
            user_id=str(kwargs["user_id"]),
            session_id="session-1",
            turn_id="turn-1",
        )

    monkeypatch.setattr(messages_dispatch, "get_runtime_system_status", _runtime_ready)
    monkeypatch.setattr(messages_dispatch, "dispatch_user_message", _fake_dispatch_user_message)
    monkeypatch.setattr(
        messages_dispatch, "build_bootstrap_l2_priority_metadata", AsyncMock(return_value={})
    )

    response = await messages_router.send_user_message(
        messages_router.UserMessageRequest(
            message="hello",
            user_id="asuka_main",
            metadata={"runtime_namespace": "telegram"},
        )
    )

    assert response.success is True
    assert captured["runtime_namespace"] == "telegram"


@pytest.mark.asyncio
async def test_send_user_message_defaults_to_desktop_runtime_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def _fake_dispatch_user_message(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return MessageDispatchOutcome(
            success=True,
            user_id=str(kwargs["user_id"]),
            session_id="session-1",
            turn_id="turn-1",
        )

    monkeypatch.setattr(messages_dispatch, "get_runtime_system_status", _runtime_ready)
    monkeypatch.setattr(messages_dispatch, "dispatch_user_message", _fake_dispatch_user_message)
    monkeypatch.setattr(
        messages_dispatch, "build_bootstrap_l2_priority_metadata", AsyncMock(return_value={})
    )

    response = await messages_router.send_user_message(
        messages_router.UserMessageRequest(
            message="hello",
            session_id="session-1",
        )
    )

    assert response.success is True
    assert captured["user_id"] == "local_user"
    assert captured["runtime_namespace"] == "desktop"


@pytest.mark.asyncio
async def test_send_user_message_forwards_structured_recall_feedback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def _fake_dispatch_user_message(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return MessageDispatchOutcome(
            success=True,
            user_id=str(kwargs["user_id"]),
            session_id="session-1",
            turn_id="turn-1",
        )

    monkeypatch.setattr(messages_dispatch, "get_runtime_system_status", _runtime_ready)
    monkeypatch.setattr(messages_dispatch, "dispatch_user_message", _fake_dispatch_user_message)
    monkeypatch.setattr(
        messages_dispatch, "build_bootstrap_l2_priority_metadata", AsyncMock(return_value={})
    )

    response = await messages_router.send_user_message(
        messages_router.UserMessageRequest(
            message="Leave this record out.",
            session_id="session-1",
            reply_to_message_id="assistant-1",
            recall_feedback={
                "kind": "item_irrelevant",
                "target_message_id": "assistant-1",
                "finding_ref": "event:event-1",
            },
        )
    )

    assert response.success is True
    assert captured["reply_to_message_id"] == "assistant-1"
    assert captured["metadata"]["recall_feedback"] == {
        "kind": "item_irrelevant",
        "target_message_id": "assistant-1",
        "finding_ref": "event:event-1",
    }


def test_item_recall_feedback_requires_a_finding_reference() -> None:
    with pytest.raises(ValidationError):
        messages_router.UserMessageRequest(
            message="Leave this record out.",
            session_id="session-1",
            recall_feedback={
                "kind": "item_irrelevant",
                "target_message_id": "assistant-1",
            },
        )


@pytest.mark.asyncio
async def test_send_user_message_passes_attachments_and_workspace_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def _fake_dispatch_user_message(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return MessageDispatchOutcome(
            success=True,
            user_id=str(kwargs["user_id"]),
            session_id="session-1",
            turn_id="turn-1",
        )

    monkeypatch.setattr(messages_dispatch, "get_runtime_system_status", _runtime_ready)
    monkeypatch.setattr(messages_dispatch, "dispatch_user_message", _fake_dispatch_user_message)
    monkeypatch.setattr(
        messages_dispatch, "build_bootstrap_l2_priority_metadata", AsyncMock(return_value={})
    )

    response = await messages_router.send_user_message(
        messages_router.UserMessageRequest(
            message="",
            session_id="session-1",
            attachments=[{"kind": "image", "attachment_id": "att-1"}],
            workspace_path="/tmp/magi",
        )
    )

    assert response.success is True
    assert captured["attachments"] == [{"kind": "image", "attachment_id": "att-1"}]
    assert captured["workspace_path"] == "/tmp/magi"


@pytest.mark.asyncio
async def test_send_user_message_forwards_reply_target(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def _fake_dispatch_user_message(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return MessageDispatchOutcome(
            success=True,
            user_id=str(kwargs["user_id"]),
            session_id="session-1",
            turn_id="turn-1",
        )

    monkeypatch.setattr(messages_dispatch, "get_runtime_system_status", _runtime_ready)
    monkeypatch.setattr(messages_dispatch, "dispatch_user_message", _fake_dispatch_user_message)
    monkeypatch.setattr(
        messages_dispatch, "build_bootstrap_l2_priority_metadata", AsyncMock(return_value={})
    )

    response = await messages_router.send_user_message(
        messages_router.UserMessageRequest(
            message="Replying here",
            session_id="session-1",
            reply_to_message_id="msg-assistant-1",
        )
    )

    assert response.success is True
    assert captured["metadata"] == {"reply_to_message_id": "msg-assistant-1"}


@pytest.mark.asyncio
async def test_send_user_message_rejects_when_runtime_is_not_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_runtime_status(_app):  # type: ignore[no-untyped-def]
        return {
            "runtime_ready": False,
            "runtime_status": "deferred",
            "startup_state": "deferred",
            "deferred_reason": "llm_selection_pending",
        }

    dispatch_called = False

    async def _fake_dispatch_user_message(**kwargs):  # type: ignore[no-untyped-def]
        nonlocal dispatch_called
        dispatch_called = True
        return MessageDispatchOutcome(
            success=True,
            user_id=str(kwargs["user_id"]),
            session_id="session-1",
            turn_id="turn-1",
        )

    monkeypatch.setattr(messages_dispatch, "get_runtime_system_status", _fake_runtime_status)
    monkeypatch.setattr(messages_dispatch, "dispatch_user_message", _fake_dispatch_user_message)
    monkeypatch.setattr(
        messages_dispatch, "build_bootstrap_l2_priority_metadata", AsyncMock(return_value={})
    )

    response = await messages_router.send_user_message(
        messages_router.UserMessageRequest(
            message="hello",
            session_id="session-1",
        )
    )

    assert response.success is False
    assert response.data["error_code"] == "RUNTIME_NOT_READY"
    assert response.data["startup_state"] == "deferred"
    assert dispatch_called is False


@pytest.mark.asyncio
async def test_send_user_message_dispatches_when_runtime_is_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def _fake_dispatch_user_message(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return MessageDispatchOutcome(
            success=True,
            user_id=str(kwargs["user_id"]),
            session_id="session-1",
            turn_id="turn-1",
        )

    monkeypatch.setattr(messages_dispatch, "get_runtime_system_status", _runtime_ready)
    monkeypatch.setattr(messages_dispatch, "dispatch_user_message", _fake_dispatch_user_message)
    monkeypatch.setattr(
        messages_dispatch, "build_bootstrap_l2_priority_metadata", AsyncMock(return_value={})
    )

    response = await messages_router.send_user_message(
        messages_router.UserMessageRequest(
            message="hello",
            session_id="session-1",
        )
    )

    assert response.success is True
    assert captured["message"] == "hello"


@pytest.mark.asyncio
async def test_send_user_message_merges_bootstrap_l2_priority_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def _fake_dispatch_user_message(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return MessageDispatchOutcome(
            success=True,
            user_id=str(kwargs["user_id"]),
            session_id="session-1",
            turn_id="turn-1",
        )

    monkeypatch.setattr(messages_dispatch, "get_runtime_system_status", _runtime_ready)
    monkeypatch.setattr(messages_dispatch, "dispatch_user_message", _fake_dispatch_user_message)
    monkeypatch.setattr(
        messages_dispatch,
        "build_bootstrap_l2_priority_metadata",
        AsyncMock(
            return_value={
                "l2_batch_owner": "bootstrap:u1:test",
                "l2_batch_max_events": 1,
                "l2_batch_min_ready_events": 1,
                "l2_batch_max_wait_seconds": 1.0,
            }
        ),
    )

    response = await messages_router.send_user_message(
        messages_router.UserMessageRequest(
            message="hello",
            user_id="u1",
            session_id="session-1",
            metadata={"runtime_namespace": "desktop"},
        )
    )

    assert response.success is True
    assert captured["metadata"] == {
        "runtime_namespace": "desktop",
        "l2_batch_owner": "bootstrap:u1:test",
        "l2_batch_max_events": 1,
        "l2_batch_min_ready_events": 1,
        "l2_batch_max_wait_seconds": 1.0,
    }


@pytest.mark.asyncio
async def test_get_conversation_history_uses_async_read_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _AsyncOnlyReadService:
        def get_display_history(self, user_id: str, session_id: str):  # type: ignore[no-untyped-def]
            raise AssertionError("sync history reader should not be used")

        async def aget_display_history(self, user_id: str, session_id: str):
            assert user_id == "u1"
            assert session_id == "s1"
            return [
                ChatDisplayMessage(
                    role="assistant",
                    content="hello",
                    timestamp=1,
                    kind="assistant",
                    reply_to={
                        "message_id": "msg-root",
                        "role": "user",
                        "message_kind": "user_text",
                        "content_excerpt": "Need the release plan",
                    },
                )
            ]

        async def aget_session_summary(self, user_id: str, session_id: str):
            assert user_id == "u1"
            assert session_id == "s1"
            return None

    monkeypatch.setattr(
        messages_content, "require_chat_read_service", lambda: _AsyncOnlyReadService()
    )

    response = await messages_router.get_conversation_history(user_id="u1", session_id="s1")

    assert response["count"] == 1
    assert response["messages"][0]["content"] == "hello"
    assert response["messages"][0]["reply_to"]["message_id"] == "msg-root"


@pytest.mark.asyncio
async def test_get_chat_attachment_content_returns_file_response(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    attachment_path = tmp_path / "diagram.png"
    attachment_path.write_bytes(b"png")

    class _AsyncOnlyReadService:
        def get_attachment_payload(self, user_id: str, session_id: str, attachment_id: str):  # type: ignore[no-untyped-def]
            raise AssertionError("sync attachment reader should not be used")

        async def aget_attachment_payload(self, user_id: str, session_id: str, attachment_id: str):
            assert user_id == "u1"
            assert session_id == "s1"
            assert attachment_id == "att-1"
            return {
                "attachment_id": "att-1",
                "original_name": "diagram.png",
                "mime_type": "image/png",
                "storage_path": str(attachment_path),
            }

    monkeypatch.setattr(
        messages_content, "require_chat_read_service", lambda: _AsyncOnlyReadService()
    )

    response = await messages_router.get_chat_attachment_content(
        session_id="s1",
        attachment_id="att-1",
        user_id="u1",
    )

    assert isinstance(response, FileResponse)
    assert str(response.path) == str(attachment_path)
    assert response.media_type == "image/png"


@pytest.mark.asyncio
async def test_set_message_label_route_updates_message_without_creating_new_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _FakeChatSurfaceWriter:
        async def set_message_label(
            self,
            *,
            user_id: str,
            session_id: str,
            message_id: str,
            label: dict[str, object],
        ) -> bool:
            captured["user_id"] = user_id
            captured["session_id"] = session_id
            captured["message_id"] = message_id
            captured["label"] = label
            return True

    monkeypatch.setattr(
        messages_mutations, "require_chat_surface_write_service", lambda: _FakeChatSurfaceWriter()
    )

    response = await messages_router.set_message_label(
        session_id="s1",
        message_id="msg-1",
        request=messages_router.MessageLabelRequest(
            user_id="u1",
            kind="emoji",
            text="👍",
            applied_by="user",
            source="manual",
            created_at_ms=123,
        ),
    )

    assert response["success"] is True
    assert captured == {
        "user_id": "u1",
        "session_id": "s1",
        "message_id": "msg-1",
        "label": {
            "kind": "emoji",
            "text": "👍",
            "applied_by": "user",
            "source": "manual",
            "created_at_ms": 123,
        },
    }


@pytest.mark.asyncio
async def test_delete_message_route_soft_deletes_existing_chat_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _FakeChatSurfaceWriter:
        async def hide_message(
            self,
            *,
            user_id: str,
            session_id: str,
            message_id: str,
        ) -> bool:
            captured["user_id"] = user_id
            captured["session_id"] = session_id
            captured["message_id"] = message_id
            return True

    monkeypatch.setattr(
        messages_mutations, "require_chat_surface_write_service", lambda: _FakeChatSurfaceWriter()
    )

    response = await messages_router.delete_message(
        session_id="s1",
        message_id="msg-1",
        user_id="u1",
    )

    assert response == {
        "success": True,
        "user_id": "u1",
        "session_id": "s1",
        "deleted_message_id": "msg-1",
    }
    assert captured == {
        "user_id": "u1",
        "session_id": "s1",
        "message_id": "msg-1",
    }


@pytest.mark.asyncio
async def test_get_execution_trace_uses_async_trace_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeReadService:
        pass

    class _AsyncOnlyTraceService:
        def get_trace_snapshot(self, *, user_id: str, session_id: str, turn_id: str):
            raise AssertionError("sync trace reader should not be used")

        async def aget_trace_snapshot(self, *, user_id: str, session_id: str, turn_id: str):
            assert user_id == "u1"
            assert session_id == "s1"
            assert turn_id == "turn-1"
            return {"summary": {"headline": "done"}}

    monkeypatch.setattr(messages_content, "require_chat_read_service", lambda: _FakeReadService())
    monkeypatch.setattr(
        messages_content, "get_chat_trace_read_service", lambda: _AsyncOnlyTraceService()
    )

    response = await messages_router.get_execution_trace(
        user_id="u1", session_id="s1", turn_id="turn-1"
    )

    assert response["success"] is True
    assert response["trace"]["summary"]["headline"] == "done"


@pytest.mark.asyncio
async def test_create_new_session_uses_default_workspace_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _FakeReadService:
        async def acreate_new_session(self, user_id: str, workspace_path: str | None = None):
            captured["user_id"] = user_id
            captured["workspace_path"] = workspace_path
            return "session-1"

    monkeypatch.setattr(messages_sessions, "require_chat_read_service", lambda: _FakeReadService())
    monkeypatch.setattr(messages_sessions, "get_default_chat_workspace_path", lambda: "/tmp/magi")

    response = await messages_router.create_new_session(user_id="u1")

    assert response["success"] is True
    assert response["session_id"] == "session-1"
    assert response["workspace_path"] == "/tmp/magi"
    assert captured["workspace_path"] == "/tmp/magi"


@pytest.mark.asyncio
async def test_update_session_workspace_route_response(monkeypatch: pytest.MonkeyPatch) -> None:
    @dataclass
    class _SessionWorkspaceUpdateResult:
        session_id: str
        workspace_path: str | None

    class _FakeReadService:
        async def aupdate_session_workspace(
            self, user_id: str, session_id: str, workspace_path: str | None
        ):
            assert user_id == "u1"
            assert session_id == "s1"
            assert workspace_path == "/tmp/magi"
            return _SessionWorkspaceUpdateResult(
                session_id="s1",
                workspace_path="/tmp/magi",
            )

    monkeypatch.setattr(messages_sessions, "require_chat_read_service", lambda: _FakeReadService())

    response = await messages_router.update_session_workspace(
        session_id="s1",
        request=messages_router.UpdateSessionWorkspaceRequest(
            user_id="u1",
            workspace_path="/tmp/magi",
        ),
    )

    assert response["success"] is True
    assert response["session"]["workspace_path"] == "/tmp/magi"


@pytest.mark.asyncio
async def test_cancel_session_run_route_delegates_to_chat_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _FakeChatAgent:
        async def request_session_cancel(
            self,
            *,
            session_id: str,
            requested_by: str,
            reason: str,
            anchor_turn_id: str | None = None,
        ) -> dict[str, object] | None:
            captured.update(
                {
                    "session_id": session_id,
                    "requested_by": requested_by,
                    "reason": reason,
                    "anchor_turn_id": anchor_turn_id,
                }
            )
            return {
                "run_id": "run-1",
                "revision": 0,
                "status": "cancelling",
                "cancelled_orchestration_ids": ["orch-1"],
            }

    class _FakeTaskAgentManager:
        async def ensure_agent(self, agent_type, agent_id):  # type: ignore[no-untyped-def]
            captured["agent_type"] = agent_type
            captured["agent_id"] = agent_id
            return _FakeChatAgent()

    class _FakeRuntime:
        def get_task_agent_manager(self) -> _FakeTaskAgentManager:
            return _FakeTaskAgentManager()

    monkeypatch.setattr(messages_run_control, "require_agent_runtime", lambda: _FakeRuntime())

    response = await messages_router.cancel_session_run(
        session_id="session-1",
        request=messages_router.CancelSessionRunRequest(
            user_id="u1",
            reason="explicit_cancel",
            turn_id="turn-cancel",
            requested_by="user",
        ),
    )

    assert response["success"] is True
    assert response["data"]["run_id"] == "run-1"
    assert response["data"]["cancelled_orchestration_ids"] == ["orch-1"]


@pytest.mark.asyncio
async def test_detach_session_run_route_delegates_to_chat_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _FakeChatAgent:
        async def request_session_detach(
            self,
            *,
            session_id: str,
            requested_by: str,
            reason: str,
            anchor_turn_id: str | None = None,
        ) -> dict[str, object] | None:
            captured.update(
                {
                    "session_id": session_id,
                    "requested_by": requested_by,
                    "reason": reason,
                    "anchor_turn_id": anchor_turn_id,
                }
            )
            return {
                "run_id": "run-1",
                "revision": 0,
                "status": "detaching",
            }

    class _FakeTaskAgentManager:
        async def ensure_agent(self, agent_type, agent_id):  # type: ignore[no-untyped-def]
            captured["agent_type"] = agent_type
            captured["agent_id"] = agent_id
            return _FakeChatAgent()

    class _FakeRuntime:
        def get_task_agent_manager(self) -> _FakeTaskAgentManager:
            return _FakeTaskAgentManager()

    monkeypatch.setattr(messages_run_control, "require_agent_runtime", lambda: _FakeRuntime())

    with language_context("en"):
        response = await messages_router.detach_session_run(
            session_id="session-1",
            request=messages_router.DetachSessionRunRequest(
                user_id="u1",
                reason="user_detach",
                turn_id="turn-detach",
                requested_by="user",
            ),
        )

    assert captured == {
        "agent_type": messages_run_control.TaskAgentType.CHAT,
        "agent_id": "session-1",
        "session_id": "session-1",
        "requested_by": "user",
        "reason": "user_detach",
        "anchor_turn_id": "turn-detach",
    }
    assert response["success"] is True
    assert response["message"] == "Run detach requested"
    assert response["data"]["status"] == "detaching"
    assert captured["session_id"] == "session-1"
    assert captured["requested_by"] == "user"
    assert captured["reason"] == "user_detach"
    assert captured["anchor_turn_id"] == "turn-detach"
