from __future__ import annotations

import pytest

from magi.api.routers import messages as messages_router
from magi.chat.read_service import ChatDisplayMessage
from magi.api.services.message_dispatch_service import MessageDispatchOutcome


@pytest.mark.asyncio
async def test_send_user_message_uses_runtime_namespace_for_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def _fake_dispatch_user_message(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return MessageDispatchOutcome(
            success=True,
            user_id=str(kwargs["user_id"]),
            session_id="session-1",
            turn_id="turn-1",
        )

    monkeypatch.setattr(messages_router, "dispatch_user_message", _fake_dispatch_user_message)

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
async def test_send_user_message_defaults_to_desktop_runtime_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def _fake_dispatch_user_message(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return MessageDispatchOutcome(
            success=True,
            user_id=str(kwargs["user_id"]),
            session_id="session-1",
            turn_id="turn-1",
        )

    monkeypatch.setattr(messages_router, "dispatch_user_message", _fake_dispatch_user_message)

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
async def test_send_user_message_passes_attachments_and_workspace_path(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def _fake_dispatch_user_message(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return MessageDispatchOutcome(
            success=True,
            user_id=str(kwargs["user_id"]),
            session_id="session-1",
            turn_id="turn-1",
        )

    monkeypatch.setattr(messages_router, "dispatch_user_message", _fake_dispatch_user_message)

    response = await messages_router.send_user_message(
        messages_router.UserMessageRequest(
            message="",
            session_id="session-1",
            attachments=[{"kind": "image", "attachment_id": "att-1"}],
            workspace_path="/Users/asuka/code/magi",
        )
    )

    assert response.success is True
    assert captured["attachments"] == [{"kind": "image", "attachment_id": "att-1"}]
    assert captured["workspace_path"] == "/Users/asuka/code/magi"


@pytest.mark.asyncio
async def test_get_conversation_history_uses_async_read_service(monkeypatch: pytest.MonkeyPatch) -> None:
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
                )
            ]

    monkeypatch.setattr(messages_router, "get_chat_read_service", lambda: _AsyncOnlyReadService())

    response = await messages_router.get_conversation_history(user_id="u1", session_id="s1")

    assert response["count"] == 1
    assert response["messages"][0]["content"] == "hello"


@pytest.mark.asyncio
async def test_get_execution_trace_uses_async_trace_service(monkeypatch: pytest.MonkeyPatch) -> None:
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

    monkeypatch.setattr(messages_router, "get_chat_read_service", lambda: _FakeReadService())
    monkeypatch.setattr(messages_router, "get_chat_trace_read_service", lambda: _AsyncOnlyTraceService())

    response = await messages_router.get_execution_trace(user_id="u1", session_id="s1", turn_id="turn-1")

    assert response["success"] is True
    assert response["trace"]["summary"]["headline"] == "done"


@pytest.mark.asyncio
async def test_create_new_session_uses_default_workspace_path(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _FakeReadService:
        async def acreate_new_session(self, user_id: str, workspace_path: str | None = None):
            captured["user_id"] = user_id
            captured["workspace_path"] = workspace_path
            return "session-1"

    monkeypatch.setattr(messages_router, "get_chat_read_service", lambda: _FakeReadService())
    monkeypatch.setattr(messages_router, "_get_default_chat_workspace_path", lambda: "/Users/asuka/code/magi")

    response = await messages_router.create_new_session(user_id="u1")

    assert response["success"] is True
    assert response["session_id"] == "session-1"
    assert response["workspace_path"] == "/Users/asuka/code/magi"
    assert captured["workspace_path"] == "/Users/asuka/code/magi"


@pytest.mark.asyncio
async def test_update_session_workspace_route_response(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeReadService:
        async def aupdate_session_workspace(self, user_id: str, session_id: str, workspace_path: str | None):
            assert user_id == "u1"
            assert session_id == "s1"
            assert workspace_path == "/Users/asuka/code/magi"
            return messages_router.SessionWorkspaceUpdateResult(
                session_id="s1",
                workspace_path="/Users/asuka/code/magi",
            )

    monkeypatch.setattr(messages_router, "get_chat_read_service", lambda: _FakeReadService())

    response = await messages_router.update_session_workspace(
        session_id="s1",
        request=messages_router.UpdateSessionWorkspaceRequest(
            user_id="u1",
            workspace_path="/Users/asuka/code/magi",
        ),
    )

    assert response["success"] is True
    assert response["session"]["workspace_path"] == "/Users/asuka/code/magi"


@pytest.mark.asyncio
async def test_cancel_session_run_route_delegates_to_chat_agent(monkeypatch: pytest.MonkeyPatch) -> None:
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

    monkeypatch.setattr(messages_router, "require_agent_runtime", lambda: _FakeRuntime())

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
    assert captured["session_id"] == "session-1"
    assert captured["requested_by"] == "user"
    assert captured["reason"] == "explicit_cancel"
    assert captured["anchor_turn_id"] == "turn-cancel"
