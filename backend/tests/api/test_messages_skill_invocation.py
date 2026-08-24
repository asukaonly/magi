from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from magi.api.routers import messages_dispatch
from magi.api.routers.messages_models import UserMessageRequest
from magi.skills.expander import SkillExpansion


def _expansion(*, context_mode: str | None = None) -> SkillExpansion:
    return SkillExpansion(
        name="review",
        rendered_prompt="Inspect the requested change carefully.",
        invocation_text="/review 123",
        description="Review a change",
        argument_hint="<id>",
        allowed_tools=["read_file"],
        context_mode=context_mode,
        user_invocable=True,
        content_hash="abc123",
    )


@pytest.mark.asyncio
async def test_inline_skill_is_dispatched_as_typed_server_context(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def _dispatch(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return SimpleNamespace(
            success=True,
            handled_as="queued",
            session_id="session-1",
            turn_id="turn-1",
            message_id="message-1",
            queue_size=1,
        )

    async def _empty_metadata(**_kwargs):  # type: ignore[no-untyped-def]
        return {}

    monkeypatch.setattr(messages_dispatch, "dispatch_user_message", _dispatch)
    monkeypatch.setattr(
        messages_dispatch,
        "build_bootstrap_l2_priority_metadata",
        _empty_metadata,
    )
    monkeypatch.setattr(messages_dispatch, "expand_skill", lambda **_kwargs: _expansion())
    monkeypatch.setattr(
        messages_dispatch,
        "get_enabled_skill_names",
        lambda: {"review"},
    )

    request = UserMessageRequest(
        session_id="session-1",
        message="frontend text is not authoritative",
        skill_invocation={"name": "review", "arguments": ["123"]},
    )
    await messages_dispatch._dispatch_api_user_message(request)

    assert captured["message"] == "/review 123"
    metadata = captured["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["skill_invocation"] == {
        "name": "review",
        "arguments": ["123"],
        "invocation_text": "/review 123",
        "rendered_prompt": "Inspect the requested change carefully.",
        "content_hash": "abc123",
        "context_mode": "inline",
        "allowed_tools": ["read_file"],
    }


def test_inline_skill_rejects_disabled_or_fork_only_skill(monkeypatch) -> None:
    request = UserMessageRequest(
        session_id="session-1",
        skill_invocation={"name": "review", "arguments": []},
    )
    monkeypatch.setattr(messages_dispatch, "expand_skill", lambda **_kwargs: _expansion())
    monkeypatch.setattr(messages_dispatch, "get_enabled_skill_names", lambda: set())
    with pytest.raises(HTTPException) as disabled:
        messages_dispatch._build_inline_skill_context(request)
    assert disabled.value.status_code == 403

    monkeypatch.setattr(messages_dispatch, "get_enabled_skill_names", lambda: {"review"})
    monkeypatch.setattr(
        messages_dispatch,
        "expand_skill",
        lambda **_kwargs: _expansion(context_mode="fork"),
    )
    with pytest.raises(HTTPException) as fork_only:
        messages_dispatch._build_inline_skill_context(request)
    assert fork_only.value.status_code == 409
