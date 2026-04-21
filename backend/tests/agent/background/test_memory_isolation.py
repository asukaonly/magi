from __future__ import annotations

from typing import Any

import pytest

from magi.agent.background.memory_isolation import (
    BACKGROUND_SCOPE_KEY,
    BackgroundFactEmitter,
    BackgroundMemoryScope,
    get_background_scope,
    is_background_fact,
    tag_fact,
)
from magi.agent.runtime.contracts import FactRecord


def _make_fact(**overrides: Any) -> FactRecord:
    defaults: dict[str, Any] = {
        "agent_id": "chat:alice",
        "event_type": "user_message",
        "payload": {"text": "hello"},
        "agent_type": "chat",
        "agent_instance_id": "alice",
        "correlation_id": "corr-1",
    }
    defaults.update(overrides)
    return FactRecord(**defaults)


# ----------------------------------------------------------------------
# BackgroundMemoryScope roundtrip
# ----------------------------------------------------------------------


def test_scope_roundtrip_preserves_fields() -> None:
    scope = BackgroundMemoryScope(
        background_task_id="bg_abc123", origin_session_id="sess_42"
    )

    roundtripped = BackgroundMemoryScope.from_dict(scope.to_dict())

    assert roundtripped == scope


def test_scope_roundtrip_without_origin() -> None:
    scope = BackgroundMemoryScope(background_task_id="bg_solo")

    roundtripped = BackgroundMemoryScope.from_dict(scope.to_dict())

    assert roundtripped == scope
    assert roundtripped.origin_session_id is None


def test_scope_from_dict_requires_task_id() -> None:
    with pytest.raises(ValueError):
        BackgroundMemoryScope.from_dict({"origin_session_id": "sess"})


def test_scope_from_dict_rejects_empty_task_id() -> None:
    with pytest.raises(ValueError):
        BackgroundMemoryScope.from_dict(
            {"background_task_id": "", "origin_session_id": "sess"}
        )


# ----------------------------------------------------------------------
# tag_fact / get_background_scope
# ----------------------------------------------------------------------


def test_tag_fact_stamps_scope_into_payload() -> None:
    fact = _make_fact()
    scope = BackgroundMemoryScope(
        background_task_id="bg_abc", origin_session_id="sess_1"
    )

    tagged = tag_fact(fact, scope)

    assert tagged.payload[BACKGROUND_SCOPE_KEY] == scope.to_dict()
    assert tagged.payload["text"] == "hello"  # existing payload preserved


def test_tag_fact_does_not_mutate_original_payload() -> None:
    fact = _make_fact()
    original_payload = dict(fact.payload)
    scope = BackgroundMemoryScope(background_task_id="bg_abc")

    _ = tag_fact(fact, scope)

    assert fact.payload == original_payload
    assert BACKGROUND_SCOPE_KEY not in fact.payload


def test_tag_fact_preserves_all_envelope_fields() -> None:
    fact = _make_fact(agent_type="explore", correlation_id="corr-xyz")
    scope = BackgroundMemoryScope(background_task_id="bg_abc")

    tagged = tag_fact(fact, scope)

    assert tagged.agent_id == fact.agent_id
    assert tagged.event_type == fact.event_type
    assert tagged.agent_type == "explore"
    assert tagged.agent_instance_id == fact.agent_instance_id
    assert tagged.timestamp == fact.timestamp
    assert tagged.correlation_id == "corr-xyz"


def test_tag_fact_is_idempotent_last_write_wins() -> None:
    fact = _make_fact()
    first = BackgroundMemoryScope(background_task_id="bg_first")
    second = BackgroundMemoryScope(background_task_id="bg_second")

    tagged = tag_fact(tag_fact(fact, first), second)

    assert get_background_scope(tagged) == second


def test_get_background_scope_returns_none_for_untagged_fact() -> None:
    assert get_background_scope(_make_fact()) is None


def test_get_background_scope_returns_none_for_non_dict_payload() -> None:
    fact = _make_fact(payload={})  # Empty dict — no scope stamped.
    assert get_background_scope(fact) is None


def test_get_background_scope_returns_none_on_malformed_stamp() -> None:
    fact = _make_fact(payload={BACKGROUND_SCOPE_KEY: "not a dict"})
    assert get_background_scope(fact) is None


def test_get_background_scope_returns_none_on_missing_task_id() -> None:
    fact = _make_fact(
        payload={BACKGROUND_SCOPE_KEY: {"origin_session_id": "sess_1"}}
    )
    assert get_background_scope(fact) is None


def test_is_background_fact_tracks_tag_presence() -> None:
    untagged = _make_fact()
    scope = BackgroundMemoryScope(background_task_id="bg_abc")
    tagged = tag_fact(untagged, scope)

    assert is_background_fact(untagged) is False
    assert is_background_fact(tagged) is True


# ----------------------------------------------------------------------
# BackgroundFactEmitter
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emitter_tags_and_forwards_fact() -> None:
    received: list[FactRecord] = []

    async def _delegate(fact: FactRecord) -> bool:
        received.append(fact)
        return True

    scope = BackgroundMemoryScope(
        background_task_id="bg_abc", origin_session_id="sess_1"
    )
    emitter = BackgroundFactEmitter(_delegate, scope)

    result = await emitter.emit(_make_fact())

    assert result is True
    assert len(received) == 1
    forwarded = received[0]
    assert get_background_scope(forwarded) == scope
    assert forwarded.payload["text"] == "hello"


@pytest.mark.asyncio
async def test_emitter_propagates_delegate_false() -> None:
    async def _delegate(_: FactRecord) -> bool:
        return False

    scope = BackgroundMemoryScope(background_task_id="bg_abc")
    emitter = BackgroundFactEmitter(_delegate, scope)

    assert await emitter.emit(_make_fact()) is False


@pytest.mark.asyncio
async def test_emitter_propagates_delegate_exceptions() -> None:
    async def _delegate(_: FactRecord) -> bool:
        raise RuntimeError("router offline")

    scope = BackgroundMemoryScope(background_task_id="bg_abc")
    emitter = BackgroundFactEmitter(_delegate, scope)

    with pytest.raises(RuntimeError, match="router offline"):
        await emitter.emit(_make_fact())


def test_emitter_exposes_scope() -> None:
    async def _delegate(_: FactRecord) -> bool:
        return True

    scope = BackgroundMemoryScope(background_task_id="bg_abc")
    emitter = BackgroundFactEmitter(_delegate, scope)

    assert emitter.scope is scope
