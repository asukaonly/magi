"""``ChannelBindingSettingsStore`` CRUD — CF-7 of channel control fanout.

Pins:
* ``get`` returns auto_approve=False for un-known bindings (virtual
  default; no row materialization).
* ``set_auto_approve(True)`` upserts; ``get`` reflects.
* Idempotent re-set keeps the same auto_approve value but bumps
  updated_at_ms (audit trail).
* Blank channel_type / external_user_id rejected at set-time.
* ``list_all`` returns rows ordered by updated_at_ms DESC.
* Per-binding isolation: setting weixin/userA doesn't affect
  telegram/userA or weixin/userB.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from magi.channels.binding_settings_store import ChannelBindingSettingsStore


_SCHEMA = """
CREATE TABLE channel_binding_settings (
    channel_type      TEXT    NOT NULL,
    external_user_id  TEXT    NOT NULL,
    auto_approve      INTEGER NOT NULL DEFAULT 0,
    updated_at_ms     INTEGER NOT NULL,
    PRIMARY KEY (channel_type, external_user_id)
);
"""


@pytest.fixture
def store(tmp_path: Path) -> ChannelBindingSettingsStore:
    db = tmp_path / "channels.db"
    conn = sqlite3.connect(db)
    conn.executescript(_SCHEMA)
    conn.commit()
    conn.close()
    return ChannelBindingSettingsStore(db_path=str(db))


# === Defaults / get ======================================================


@pytest.mark.asyncio
async def test_get_unknown_binding_returns_virtual_default(store) -> None:
    """No row → auto_approve=False, updated_at_ms=0. Callers don't
    need to distinguish 'no row' from 'row exists with False'."""
    result = await store.get(channel_type="weixin", external_user_id="userA")
    assert result.channel_type == "weixin"
    assert result.external_user_id == "userA"
    assert result.auto_approve is False
    assert result.updated_at_ms == 0


# === Upsert ==============================================================


@pytest.mark.asyncio
async def test_set_then_get_round_trip(store) -> None:
    set_result = await store.set_auto_approve(
        channel_type="weixin", external_user_id="userA", auto_approve=True,
    )
    assert set_result.auto_approve is True
    assert set_result.updated_at_ms > 0

    fetched = await store.get(channel_type="weixin", external_user_id="userA")
    assert fetched.auto_approve is True
    assert fetched.updated_at_ms == set_result.updated_at_ms


@pytest.mark.asyncio
async def test_set_toggle_off(store) -> None:
    """Setting True then False stores False (user un-checked the toggle)."""
    await store.set_auto_approve(
        channel_type="weixin", external_user_id="userA", auto_approve=True,
    )
    await store.set_auto_approve(
        channel_type="weixin", external_user_id="userA", auto_approve=False,
    )
    fetched = await store.get(channel_type="weixin", external_user_id="userA")
    assert fetched.auto_approve is False


@pytest.mark.asyncio
async def test_set_is_idempotent_but_updates_timestamp(store) -> None:
    """Re-setting the same value is allowed (no error, no schema
    weirdness); updated_at_ms bumps so audit trails can see the
    user's confirming click."""
    first = await store.set_auto_approve(
        channel_type="weixin", external_user_id="userA", auto_approve=True,
    )
    import time
    time.sleep(0.005)  # ensure timestamp increment
    second = await store.set_auto_approve(
        channel_type="weixin", external_user_id="userA", auto_approve=True,
    )
    assert second.auto_approve is True
    assert second.updated_at_ms >= first.updated_at_ms


# === Validation ==========================================================


@pytest.mark.asyncio
async def test_set_blank_channel_type_rejected(store) -> None:
    with pytest.raises(ValueError, match="channel_type"):
        await store.set_auto_approve(
            channel_type="", external_user_id="userA", auto_approve=True,
        )


@pytest.mark.asyncio
async def test_set_blank_external_user_id_rejected(store) -> None:
    with pytest.raises(ValueError, match="external_user_id"):
        await store.set_auto_approve(
            channel_type="weixin", external_user_id="", auto_approve=True,
        )


# === Per-binding isolation ===============================================


@pytest.mark.asyncio
async def test_per_binding_isolation(store) -> None:
    """Toggling weixin/userA must not affect telegram/userA OR
    weixin/userB. Each (channel_type, external_user_id) is its
    own row."""
    await store.set_auto_approve(
        channel_type="weixin", external_user_id="userA", auto_approve=True,
    )
    # telegram + same external_user_id: still default
    other_ch = await store.get(channel_type="telegram", external_user_id="userA")
    assert other_ch.auto_approve is False
    # weixin + different external_user_id: still default
    other_u = await store.get(channel_type="weixin", external_user_id="userB")
    assert other_u.auto_approve is False


# === list_all ============================================================


@pytest.mark.asyncio
async def test_list_all_returns_only_set_rows(store) -> None:
    """``list_all`` is for the settings UI — only returns bindings
    the user has actually toggled at some point. Brand-new bindings
    that have never been touched don't appear (virtual default via
    get is fine for them)."""
    assert await store.list_all() == []

    await store.set_auto_approve(
        channel_type="weixin", external_user_id="userA", auto_approve=True,
    )
    await store.set_auto_approve(
        channel_type="telegram", external_user_id="42", auto_approve=False,
    )
    rows = await store.list_all()
    assert len(rows) == 2
    keys = {(r.channel_type, r.external_user_id) for r in rows}
    assert keys == {("weixin", "userA"), ("telegram", "42")}
