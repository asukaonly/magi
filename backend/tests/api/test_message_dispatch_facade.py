from __future__ import annotations

import pytest

from magi.api.services import message_dispatch_service as service
from magi.events.user_message_dispatch import MessageDispatchOutcome


@pytest.mark.asyncio
async def test_dispatch_user_message_forwards_to_bound_dispatcher(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    async def _fake_dispatcher(**kwargs):  # type: ignore[no-untyped-def]
        calls.append(dict(kwargs))
        return MessageDispatchOutcome(success=True, user_id=str(kwargs["user_id"]), session_id="s1")

    monkeypatch.setattr(service, "require_user_message_dispatcher", lambda: _fake_dispatcher)

    outcome = await service.dispatch_user_message(
        source="api",
        user_id="u1",
        message="hello",
        session_id="s1",
    )

    assert outcome.success is True
    assert calls == [
        {
            "source": "api",
            "user_id": "u1",
            "message": "hello",
            "session_id": "s1",
            "attachments": None,
            "reply_to_message_id": None,
            "workspace_path": None,
            "client_turn_id": None,
            "metadata": None,
            "runtime_namespace": None,
            "interaction_kind": None,
            "first_context": None,
        }
    ]


@pytest.mark.asyncio
async def test_dispatch_user_message_reports_missing_dispatcher(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        service,
        "require_user_message_dispatcher",
        lambda: (_ for _ in ()).throw(RuntimeError("missing")),
    )

    outcome = await service.dispatch_user_message(
        source="api",
        user_id="u1",
        message="hello",
        session_id="s1",
    )

    assert outcome.success is False
    assert outcome.error_code == service.MESSAGE_DISPATCHER_NOT_INITIALIZED
