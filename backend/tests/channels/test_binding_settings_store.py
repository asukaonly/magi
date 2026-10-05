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
async def test_unknown_binding_is_virtual_and_does_not_materialize_a_row(store):
    from magi.channels.binding_settings_store import ChannelBindingSettings

    assert await store.list_all() == []
    assert await store.get(
        channel_type="weixin", external_user_id="userA"
    ) == ChannelBindingSettings(
        channel_type="weixin", external_user_id="userA", auto_approve=False, updated_at_ms=0
    )
    assert await store.list_all() == []


# === Upsert ==============================================================


# === Validation ==========================================================


@pytest.mark.parametrize(
    "invalid_field,channel_value,user_value",
    [
        pytest.param("channel_type", "", "userA", id="set_blank_channel_type_rejected"),
        pytest.param("external_user_id", "weixin", "", id="set_blank_external_user_id_rejected"),
    ],
)
@pytest.mark.asyncio
async def test_binding_rejects_blank_identity_fields(
    store, invalid_field, channel_value, user_value
) -> None:
    with pytest.raises(ValueError, match=invalid_field):
        await store.set_auto_approve(
            channel_type=channel_value, external_user_id=user_value, auto_approve=True
        )


# === Per-binding isolation ===============================================


@pytest.mark.asyncio
async def test_binding_upsert_refreshes_audit_time_without_touching_other_bindings(
    store, monkeypatch
):
    from types import SimpleNamespace
    from magi.channels.binding_settings_store import ChannelBindingSettings

    clock = SimpleNamespace(now=100)
    monkeypatch.setattr(
        "magi.channels.binding_settings_store.time", SimpleNamespace(time=lambda: clock.now)
    )
    identities = [("weixin", "userA"), ("telegram", "userA"), ("weixin", "userB")]
    expected = {}
    for index, (channel, user) in enumerate(identities):
        clock.now = 100 + index
        row = await store.set_auto_approve(
            channel_type=channel, external_user_id=user, auto_approve=True
        )
        expected[(channel, user)] = ChannelBindingSettings(
            channel, user, True, (100 + index) * 1000
        )
        assert row == expected[(channel, user)]
    for timestamp, enabled in [(200, True), (300, False)]:
        clock.now = timestamp
        expected[identities[0]] = ChannelBindingSettings(
            "weixin", "userA", enabled, timestamp * 1000
        )
        assert (
            await store.set_auto_approve(
                channel_type="weixin", external_user_id="userA", auto_approve=enabled
            )
            == expected[identities[0]]
        )
        for channel, user in identities:
            assert (
                await store.get(channel_type=channel, external_user_id=user)
                == expected[(channel, user)]
            )
        assert await store.list_all() == [expected[identities[i]] for i in (0, 2, 1)]


# === list_all ============================================================
