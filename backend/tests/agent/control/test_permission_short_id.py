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


@pytest.mark.parametrize("explicit,expected", [("", "ab12cd"), ("custom", "custom")])
def test_short_id_derivation_and_serialization(explicit, expected):
    req = _make_request(request_id="a" * 26 + "AB12CD", short_id=explicit)
    assert req.short_id == expected
    assert req.to_dict()["short_id"] == expected


def test_derive_short_id_static_matches_post_init() -> None:
    """``derive_short_id`` is exposed for callers that need to
    compute the short_id before the request exists; it MUST match
    what __post_init__ produces."""
    rid = "01HFTGSM7Z8X9YQK4PVAN3RBCD"
    derived = PermissionRequest.derive_short_id(rid)
    req = _make_request(request_id=rid)
    assert derived == req.short_id


# === Registry.find_by_short_id ===========================================


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "token,session,matched",
    [
        ("ab12cd", "s1", True),
        ("AB12CD", "s1", True),
        ("ab12cd", "s2", False),
        ("nope01", "s1", False),
        ("", "s1", False),
        ("   ", "s1", False),
    ],
)
async def test_short_id_lookup_is_case_insensitive_and_session_scoped(token, session, matched):
    registry = PendingPermissionRegistry()
    req = _make_request(request_id="a" * 26 + "AB12CD", session_id="s1")
    await registry.add(req)
    assert registry.find_by_short_id(token, session_id=session) is (req if matched else None)


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
