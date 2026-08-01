"""End-to-end pin of the cross-channel-memory-recall fix.

Reproduces the original production failure: weixin inbound + desktop
inbound end up under DIFFERENT user_id partitions, so neither surface
can see the other's memory. After the L1 identity layer + the four
ingress-site canonicalizations, both paths converge on
``CANONICAL_LOCAL_USER`` and downstream queries that filter by
user_id see the union of both histories.

This is an INTEGRATION test, not a full e2e: we exercise the actual
ingress code paths (``session_mapper.resolve_or_create`` for the
external-channel ingress; ``canonicalize_user_id`` for the
desktop/api ingress) and assert their outputs converge, without
spinning up the full bootstrap (message bus, runtime command queue,
agent runtime, sensor hub) that a true e2e would require. The
unit-level coverage of each ingress site is already in
``test_identity.py``, ``test_channels.py``, and
``test_sensor_hub_source_propagation.py``; this file is the
end-to-end story those individual tests tell collectively.
"""
from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from magi.channels.session_mapper import ChannelSessionMapper
from magi.identity import (
    CANONICAL_LOCAL_USER,
    ExternalIdentity,
    IdentityBindingsStore,
    LocalUserResolver,
    canonicalize_user_id,
)
from magi_plugin_sdk.channels import (
    ChannelInboundContext,
    ChannelProviderTimeEvidence,
)


_CHANNELS_SCHEMA = """
CREATE TABLE channel_session_mappings (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_type      TEXT    NOT NULL,
    external_chat_id  TEXT    NOT NULL,
    magi_session_id   TEXT    NOT NULL,
    magi_user_id      TEXT    NOT NULL,
    is_group          INTEGER NOT NULL DEFAULT 0,
    created_at_ms     INTEGER NOT NULL,
    last_active_at_ms INTEGER NOT NULL,
    metadata_json     TEXT    NOT NULL DEFAULT '{}',
    UNIQUE(channel_type, external_chat_id)
);
"""
_IDENTITY_SCHEMA = """
CREATE TABLE user_identity_bindings (
    channel_type      TEXT    NOT NULL,
    external_user_id  TEXT    NOT NULL,
    magi_user_id      TEXT    NOT NULL,
    created_at_ms     INTEGER NOT NULL,
    last_seen_at_ms   INTEGER NOT NULL,
    UNIQUE(channel_type, external_user_id)
);
"""


class _FakeSessionProvisioner:
    async def create_channel_session(self, **kwargs):  # type: ignore[no-untyped-def]
        return "chsess_identity_test"

    async def is_channel_session_available(
        self,
        *,
        magi_user_id: str,
        session_id: str,
    ) -> bool:
        del magi_user_id, session_id
        return True


class _AllowingBoundary:
    @asynccontextmanager
    async def operation(self, _context, **_kwargs):
        yield


@pytest.mark.asyncio
async def test_weixin_and_desktop_inbounds_converge_on_canonical_user(
    tmp_path: Path,
) -> None:
    """The bug this design exists to fix.

    Before: weixin inbound landed under user_id="channel_weixin_o9cq…"
            desktop inbound landed under user_id="local_user"
            → memory.user_id-keyed queries returned disjoint sets.
    After:  both paths produce ``CANONICAL_LOCAL_USER`` ("local_user")
            → memory queries see the union.
    """
    # === Setup: shared identity store (one IdentityResolver) ==============
    identity_db = tmp_path / "identity.db"
    sqlite3.connect(identity_db).executescript(_IDENTITY_SCHEMA)
    resolver = LocalUserResolver(
        bindings_store=IdentityBindingsStore(db_path=str(identity_db)),
    )

    # === Path 1: weixin inbound through session_mapper (ingress #1) =======
    channels_db = tmp_path / "channels.db"
    sqlite3.connect(channels_db).executescript(_CHANNELS_SCHEMA)
    mapper = ChannelSessionMapper(
        db_path=str(channels_db),
        session_provisioner=_FakeSessionProvisioner(),
        ingress_boundary=_AllowingBoundary(),  # type: ignore[arg-type]
        identity_resolver=resolver,
    )
    await mapper.initialize()

    weixin_mapping = await mapper.resolve_or_create(
        inbound_context=ChannelInboundContext(
            channel_type="weixin",
            stream_id="weixin-account",
            admission_evidence=ChannelProviderTimeEvidence(
                provider_occurred_at_ms=1,
            ),
            clear_generation=0,
        ),
        channel_type="weixin",
        external_chat_id="o9cq805VkoHSU8CcaDYe0iaJa-DM@im.wechat",
        external_user_id="o9cq805VkoHSU8CcaDYe0iaJa-DM@im.wechat",
    )

    # === Path 2: desktop inbound via api dispatch ingress (ingress #4) ====
    # The desktop path doesn't go through session_mapper — it gets a
    # user_id form arg from HTTP and runs it through canonicalize_user_id
    # at chat ingress entry. Simulate that.
    desktop_user_id_raw = "local_user"  # what api default supplies
    desktop_canonical = canonicalize_user_id(desktop_user_id_raw)

    # === Convergence: both paths land on CANONICAL_LOCAL_USER =============
    assert weixin_mapping.magi_user_id == str(CANONICAL_LOCAL_USER)
    assert desktop_canonical == CANONICAL_LOCAL_USER
    assert weixin_mapping.magi_user_id == str(desktop_canonical)


@pytest.mark.asyncio
async def test_legacy_channel_prefixed_string_collapses_at_canonicalize(
    tmp_path: Path,
) -> None:
    """Even if a legacy producer (pre-identity-layer code, stale fact
    record, hand-crafted test payload) leaks a ``channel_*``-prefixed
    user_id into the system AFTER the identity layer lands, the
    awareness ingress (sensor_hub) calls canonicalize_user_id and
    collapses it — so downstream memory writes still see canonical.
    """
    leaked = "channel_telegram_legacy_user_42"
    assert canonicalize_user_id(leaked) == CANONICAL_LOCAL_USER


@pytest.mark.asyncio
async def test_multiple_weixin_users_collapse_to_same_canonical(
    tmp_path: Path,
) -> None:
    """In single-user mode (the LocalUserResolver), TWO DIFFERENT
    weixin OpenIDs both collapse to CANONICAL_LOCAL_USER. That matches
    the deployment model today: "this magi instance belongs to one
    human; whichever account they write from on whichever channel,
    it's still them".

    When multi-user mode lands (BindingTableResolver), this same test
    would still pass for users explicitly bound to the canonical
    local user, and would diverge only after an explicit rebind via
    the future "connected accounts" UI.
    """
    identity_db = tmp_path / "identity.db"
    sqlite3.connect(identity_db).executescript(_IDENTITY_SCHEMA)
    resolver = LocalUserResolver(
        bindings_store=IdentityBindingsStore(db_path=str(identity_db)),
    )

    alice = await resolver.resolve(
        ExternalIdentity(channel_type="weixin", external_user_id="alice@openid"),
    )
    bob = await resolver.resolve(
        ExternalIdentity(channel_type="weixin", external_user_id="bob@openid"),
    )
    assert alice == bob == CANONICAL_LOCAL_USER

    # Forensically, the bindings table records BOTH external accounts
    # mapped to the same canonical user. Useful for a future
    # "connected accounts" UI.
    externals = await resolver.lookup_externals(CANONICAL_LOCAL_USER)
    assert {e.external_user_id for e in externals} == {
        "alice@openid", "bob@openid",
    }
