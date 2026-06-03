"""``PermissionRequest.short_id`` derivation + ``PendingPermissionRegistry``
short_id lookup — CF-2 of the channel control fanout work.

The short_id is the human-typeable correlation token a WeChat /
Telegram user types in ``/approve <short_id>`` to resolve a pending
approval prompt. It MUST:

* Derive deterministically from ``request_id`` (so the prompter, the
  fanout payload, and the slash-command parser all compute the same
  6-char tail without coordination).
* Round-trip through ``to_dict()`` (so the SSE / WebSocket payload
  and the channel ControlRequest payload both carry it).
* Be looked up in the registry scoped to a single session — the only
  guarantee against cross-session collisions is the session_id
  filter on the parser side.
"""
from __future__ import annotations

import pytest

from magi.control.permission.brokered_prompter import PendingPermissionRegistry
from magi.control.permission.contracts import (
    PermissionRequest,
    RiskLevel,
    ToolOrigin,
)


def _make_request(
    *, request_id: str | None = None, session_id: str | None = "sess-1",
    short_id: str = "",
) -> PermissionRequest:
    return PermissionRequest(
        request_id=request_id or PermissionRequest.new_id(),
        tool_name="image_gen",
        arguments={},
        risk_level=RiskLevel.MEDIUM,
        origin=ToolOrigin.CHAT,
        agent_id="agent",
        session_id=session_id,
        turn_id=None,
        workspace=None,
        short_id=short_id,
    )


# === short_id derivation =================================================


def test_short_id_derives_from_request_id_tail_lowercased() -> None:
    """Auto-derived short_id is the last 6 chars of request_id,
    lowercased. Deterministic so prompter / fanout / parser all
    agree without coordination."""
    req = _make_request(request_id="abcDEF0123456789ABCDEF0123456789")
    assert req.short_id == "456789"  # lowercased + tail


def test_short_id_explicit_value_is_honored() -> None:
    """If a caller explicitly passes short_id (e.g. test fixtures
    that want stable IDs), __post_init__ leaves it alone."""
    req = _make_request(request_id="x" * 32, short_id="custom")
    assert req.short_id == "custom"


def test_derive_short_id_static_matches_post_init() -> None:
    """``derive_short_id`` is exposed for callers that need to
    compute the short_id before the request exists; it MUST match
    what __post_init__ produces."""
    rid = "01HFTGSM7Z8X9YQK4PVAN3RBCD"
    derived = PermissionRequest.derive_short_id(rid)
    req = _make_request(request_id=rid)
    assert derived == req.short_id


def test_short_id_in_to_dict() -> None:
    """The wire payload (sent to desktop SSE + channel ControlRequest
    fanout) carries short_id so every receiver can render the
    `/approve <short_id>` hint."""
    req = _make_request()
    payload = req.to_dict()
    assert "short_id" in payload
    assert payload["short_id"] == req.short_id


# === Registry.find_by_short_id ===========================================


@pytest.mark.asyncio
async def test_find_by_short_id_returns_match_in_same_session() -> None:
    """Happy path: pending request in session s1 is looked up by
    its short_id with session_id=s1."""
    registry = PendingPermissionRegistry()
    req = _make_request(session_id="s1")
    await registry.add(req)
    assert registry.find_by_short_id(req.short_id, session_id="s1") is req


@pytest.mark.asyncio
async def test_find_by_short_id_returns_none_when_no_match() -> None:
    """No pending request → None (not an exception). Slash-command
    parser surfaces a friendly 'no such pending request' reply."""
    registry = PendingPermissionRegistry()
    assert registry.find_by_short_id("nope01", session_id="s1") is None


@pytest.mark.asyncio
async def test_find_by_short_id_does_not_leak_across_sessions() -> None:
    """A request in session s1 must NOT be found when the parser
    passes session_id=s2 — even if the short_id matches. Otherwise
    a WeChat user in session A could accidentally approve a request
    raised by a Telegram user in session B."""
    registry = PendingPermissionRegistry()
    req = _make_request(session_id="s1")
    await registry.add(req)
    assert registry.find_by_short_id(req.short_id, session_id="s2") is None


@pytest.mark.asyncio
async def test_find_by_short_id_case_insensitive() -> None:
    """Users may type uppercase — be forgiving. The short_id is
    stored lowercased; lookup lowercases the needle."""
    registry = PendingPermissionRegistry()
    req = _make_request(session_id="s1")
    await registry.add(req)
    upper = req.short_id.upper()
    assert registry.find_by_short_id(upper, session_id="s1") is req


@pytest.mark.asyncio
async def test_find_by_short_id_ambiguous_returns_none_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Two pending requests in the same session sharing a short_id
    (astronomically unlikely but possible): return None and log,
    so the slash-command handler can tell the user 'multiple
    matches, please respond on desktop' instead of guessing."""
    registry = PendingPermissionRegistry()
    # Force the same short_id by constructing two requests whose
    # last 6 hex chars collide.
    req_a = _make_request(request_id="a" * 26 + "abcdef", session_id="s1")
    req_b = _make_request(request_id="b" * 26 + "ABCDEF", session_id="s1")
    assert req_a.short_id == req_b.short_id == "abcdef"
    await registry.add(req_a)
    await registry.add(req_b)
    with caplog.at_level("WARNING"):
        result = registry.find_by_short_id("abcdef", session_id="s1")
    assert result is None
    assert any("ambiguous" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_find_by_short_id_blank_input_returns_none() -> None:
    """Empty / whitespace-only short_id never matches — defensive
    against a slash-command like ``/approve   `` with nothing after."""
    registry = PendingPermissionRegistry()
    req = _make_request(session_id="s1")
    await registry.add(req)
    assert registry.find_by_short_id("", session_id="s1") is None
    assert registry.find_by_short_id("   ", session_id="s1") is None
