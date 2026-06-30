"""Unit tests for the identity layer.

Three concerns covered:

* ``ExternalIdentity`` value semantics (blank rejection, equality).
* ``IdentityBindingsStore`` CRUD (insert, idempotent re-bind, lookup
  by external + reverse lookup by canonical, ``UNIQUE`` constraint).
* Resolver behavior — ``LocalUserResolver`` collapses everything to
  CANONICAL_LOCAL_USER even when bindings_store holds non-canonical
  rows; ``BindingTableResolver`` honors bindings and auto-binds new
  externals to CANONICAL_LOCAL_USER (single-user default).

The bindings store schema is set up directly via SQL (the alembic
v1 baseline), so these tests don't depend on the
alembic runner — they're pure unit tests of the store + resolver
classes.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from magi.identity import (
    CANONICAL_LOCAL_USER,
    BindingTableResolver,
    ExternalIdentity,
    IdentityBindingsStore,
    LocalUserResolver,
    MagiUserID,
    canonicalize_user_id,
)


# Schema copied from db/migrations/identity/versions/v1_initial.py;
# duplication is intentional — tests should not depend on alembic
# infrastructure to verify the store works.
_SCHEMA = """
CREATE TABLE user_identity_bindings (
    channel_type      TEXT    NOT NULL,
    external_user_id  TEXT    NOT NULL,
    magi_user_id      TEXT    NOT NULL,
    created_at_ms     INTEGER NOT NULL,
    last_seen_at_ms   INTEGER NOT NULL,
    UNIQUE(channel_type, external_user_id)
);
CREATE INDEX idx_user_identity_bindings_magi_user
    ON user_identity_bindings(magi_user_id);
"""


@pytest.fixture
def store(tmp_path: Path) -> IdentityBindingsStore:
    db_path = tmp_path / "identity.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)
    conn.commit()
    conn.close()
    return IdentityBindingsStore(db_path=str(db_path))


# === ExternalIdentity value semantics =====================================


def test_external_identity_rejects_blank_channel_type():
    """Blank channel_type is invalid — it would silently bind to the
    wrong row group."""
    with pytest.raises(ValueError, match="channel_type must be non-empty"):
        ExternalIdentity(channel_type="", external_user_id="x")
    with pytest.raises(ValueError, match="channel_type must be non-empty"):
        ExternalIdentity(channel_type="   ", external_user_id="x")


def test_external_identity_rejects_blank_external_user_id():
    """Blank external_user_id has no resolution semantics."""
    with pytest.raises(ValueError, match="external_user_id must be non-empty"):
        ExternalIdentity(channel_type="weixin", external_user_id="")


def test_external_identity_equality_is_value_based():
    """Frozen dataclass → hashable + equal-by-value."""
    a = ExternalIdentity(channel_type="weixin", external_user_id="o9cq")
    b = ExternalIdentity(channel_type="weixin", external_user_id="o9cq")
    c = ExternalIdentity(channel_type="telegram", external_user_id="o9cq")
    assert a == b
    assert hash(a) == hash(b)
    assert a != c
    assert {a, b, c} == {a, c}  # b dedups against a


# === canonicalize_user_id helper (ingress defense) =======================


def test_canonicalize_user_id_none_or_empty_returns_canonical():
    """Missing user_id at ingress collapses to canonical local user.
    Matches the legacy ``DEFAULT_USER_ID`` fallback semantics."""
    assert canonicalize_user_id(None) == CANONICAL_LOCAL_USER
    assert canonicalize_user_id("") == CANONICAL_LOCAL_USER
    assert canonicalize_user_id("   ") == CANONICAL_LOCAL_USER


def test_canonicalize_user_id_channel_prefix_collapses():
    """Channel-prefixed user_ids (legacy stale data flowing past
    session_mapper) collapse to canonical — the same behavior the L2
    entity helper was doing locally."""
    assert canonicalize_user_id("channel_weixin_o9cq") == CANONICAL_LOCAL_USER
    assert canonicalize_user_id("channel_telegram_42") == CANONICAL_LOCAL_USER


def test_canonicalize_user_id_canonical_passes_through():
    """Canonical inputs are returned unchanged (single-user mode)."""
    assert canonicalize_user_id("local_user") == CANONICAL_LOCAL_USER
    assert canonicalize_user_id(str(CANONICAL_LOCAL_USER)) == CANONICAL_LOCAL_USER


def test_canonicalize_user_id_non_default_honored_in_single_user():
    """Non-default, non-channel-prefix value is honored (single-user
    mode trusts the caller). Multi-user mode would route through
    the resolver instead."""
    assert canonicalize_user_id("alice") == "alice"


# === Default ownership invariant ==========================================


def test_user_profile_default_user_id_is_canonical():
    """Same invariant for ``user_profile.models.DEFAULT_USER_ID``.
    The user-profile surface historically declared the bare string
    independently; this prevents that duplicate from drifting back."""
    from magi.user_profile.models import DEFAULT_USER_ID as profile_default
    assert profile_default is CANONICAL_LOCAL_USER


# === IdentityBindingsStore CRUD ===========================================


@pytest.mark.asyncio
async def test_lookup_returns_none_when_no_binding(store):
    ext = ExternalIdentity(channel_type="weixin", external_user_id="never_seen")
    assert await store.lookup(ext) is None


@pytest.mark.asyncio
async def test_bind_then_lookup_round_trip(store):
    ext = ExternalIdentity(channel_type="weixin", external_user_id="o9cq")
    binding = await store.bind(ext, CANONICAL_LOCAL_USER)
    assert binding.channel_type == "weixin"
    assert binding.external_user_id == "o9cq"
    assert binding.magi_user_id == CANONICAL_LOCAL_USER
    assert binding.created_at_ms > 0
    assert binding.last_seen_at_ms >= binding.created_at_ms

    looked_up = await store.lookup(ext)
    assert looked_up == binding


@pytest.mark.asyncio
async def test_bind_is_idempotent_first_binding_wins(store):
    """Re-binding the same external to a DIFFERENT magi_user_id must
    honor the first binding (not blindly overwrite). Rebinding is an
    explicit operation that goes through a separate API — until that
    lands, first-wins prevents accidental identity swaps."""
    ext = ExternalIdentity(channel_type="weixin", external_user_id="o9cq")
    first = await store.bind(ext, CANONICAL_LOCAL_USER)
    second = await store.bind(ext, MagiUserID("alice"))
    assert second.magi_user_id == CANONICAL_LOCAL_USER  # first wins
    assert second.created_at_ms == first.created_at_ms  # row not recreated
    # last_seen_at_ms touched on every bind call (idempotent touch).
    assert second.last_seen_at_ms >= first.last_seen_at_ms


@pytest.mark.asyncio
async def test_lookup_externals_returns_all_bound_to_user(store):
    """Reverse lookup: given a MagiUserID, list every external that
    points to it. Used by the future 'connected accounts' UI."""
    e1 = ExternalIdentity(channel_type="weixin", external_user_id="o9cq")
    e2 = ExternalIdentity(channel_type="telegram", external_user_id="42")
    e3 = ExternalIdentity(channel_type="weixin", external_user_id="other")
    await store.bind(e1, CANONICAL_LOCAL_USER)
    await store.bind(e2, CANONICAL_LOCAL_USER)
    await store.bind(e3, MagiUserID("alice"))

    locals_ = await store.lookup_externals(CANONICAL_LOCAL_USER)
    assert set(locals_) == {e1, e2}

    alices = await store.lookup_externals(MagiUserID("alice"))
    assert alices == [e3]


# === LocalUserResolver behavior ===========================================


@pytest.mark.asyncio
async def test_local_user_resolver_collapses_everything(store):
    """The whole point of LocalUserResolver: every external maps to
    CANONICAL_LOCAL_USER, regardless of what's in the bindings table."""
    resolver = LocalUserResolver(bindings_store=store)
    e1 = ExternalIdentity(channel_type="weixin", external_user_id="o9cq")
    e2 = ExternalIdentity(channel_type="telegram", external_user_id="42")
    assert await resolver.resolve(e1) == CANONICAL_LOCAL_USER
    assert await resolver.resolve(e2) == CANONICAL_LOCAL_USER
    # Forensic binding was recorded.
    assert await store.lookup(e1) is not None
    assert await store.lookup(e2) is not None


@pytest.mark.asyncio
async def test_local_user_resolver_ignores_explicit_non_canonical_bind(store):
    """Even if someone calls .bind(ext, MagiUserID('alice')), the
    next .resolve(ext) returns CANONICAL_LOCAL_USER. The store accepts
    the (forensic) bind but resolution policy in single-user mode
    is hard-coded canonical."""
    resolver = LocalUserResolver(bindings_store=store)
    ext = ExternalIdentity(channel_type="weixin", external_user_id="o9cq")
    await resolver.bind(ext, MagiUserID("alice"))  # forensic record
    assert await resolver.resolve(ext) == CANONICAL_LOCAL_USER


@pytest.mark.asyncio
async def test_local_user_resolver_canonical_local_is_pure(store):
    """``canonical_local()`` must not touch I/O — callers may use it
    at construction time before async context exists."""
    resolver = LocalUserResolver(bindings_store=store)
    assert resolver.canonical_local() == CANONICAL_LOCAL_USER


@pytest.mark.asyncio
async def test_local_user_resolver_swallows_store_failures(store, monkeypatch):
    """Identity resolution must never break inbound processing — if
    the bindings store is corrupt / locked / disk-full, resolve()
    still returns CANONICAL_LOCAL_USER."""
    async def broken_bind(*args, **kwargs):
        raise RuntimeError("disk full")
    monkeypatch.setattr(store, "bind", broken_bind)
    resolver = LocalUserResolver(bindings_store=store)
    ext = ExternalIdentity(channel_type="weixin", external_user_id="o9cq")
    assert await resolver.resolve(ext) == CANONICAL_LOCAL_USER


# === BindingTableResolver behavior ========================================


@pytest.mark.asyncio
async def test_binding_table_resolver_returns_bound_user(store):
    """In multi-user mode, an explicit bind decides resolution."""
    resolver = BindingTableResolver(bindings_store=store)
    ext = ExternalIdentity(channel_type="weixin", external_user_id="o9cq")
    await resolver.bind(ext, MagiUserID("alice"))
    assert await resolver.resolve(ext) == MagiUserID("alice")


@pytest.mark.asyncio
async def test_binding_table_resolver_auto_binds_to_local(store):
    """An unbound external auto-binds to CANONICAL_LOCAL_USER on first
    resolve — preserves single-user-default behavior. Switching the
    resolver does NOT change which user a brand-new account lands on;
    only an explicit rebind via the future UI does."""
    resolver = BindingTableResolver(bindings_store=store)
    ext = ExternalIdentity(channel_type="weixin", external_user_id="brand_new")
    assert await resolver.resolve(ext) == CANONICAL_LOCAL_USER
    # The auto-bind got recorded.
    binding = await store.lookup(ext)
    assert binding is not None
    assert binding.magi_user_id == CANONICAL_LOCAL_USER


@pytest.mark.asyncio
async def test_binding_table_resolver_subsequent_resolve_uses_existing(store):
    """The auto-bind is sticky — subsequent resolves return the same
    MagiUserID even if defaults shift later."""
    resolver = BindingTableResolver(bindings_store=store)
    ext = ExternalIdentity(channel_type="telegram", external_user_id="42")
    first = await resolver.resolve(ext)
    second = await resolver.resolve(ext)
    assert first == second == CANONICAL_LOCAL_USER
