"""Unit tests for entity_id → human-readable display fallback (Round 4 / C2).

Phase 5's drop-if-unresolved policy was too aggressive on fresh/partial
entity_catalog deployments. This helper provides a middle ground:
- canonical_name from catalog wins (best display)
- else parse entity_id slug (good display when slug is human-readable)
- else show '(unnamed {type})' (passable when slug is hash-like)
- else drop (safe Phase 5 invariant when entity_id format is broken)
"""

from __future__ import annotations

import pytest

from magi.memory.entity_display import (
    display_name_for,
    is_hash_like_slug,
    parse_entity_id,
)


# ---- parse_entity_id ----

def test_parse_user_local_user():
    assert parse_entity_id("user:local_user") == ("user", "local_user")


def test_parse_topic_rust():
    assert parse_entity_id("topic:rust") == ("topic", "rust")


def test_parse_org_with_hash():
    assert parse_entity_id("organization:74f953b57f75") == ("organization", "74f953b57f75")


def test_parse_presence_with_account_prefix():
    assert parse_entity_id("presence:account_a1b2c3d4") == ("presence", "account_a1b2c3d4")


def test_parse_no_colon_returns_none():
    assert parse_entity_id("bare_hash_no_type") is None


def test_parse_empty_returns_none():
    assert parse_entity_id("") is None


def test_parse_only_colon_returns_none():
    assert parse_entity_id(":") is None


def test_parse_multiple_colons_keeps_first_split():
    """Some entity_ids may have colons in the slug; only split on the first."""
    assert parse_entity_id("preference:address_form:子涵") == ("preference", "address_form:子涵")


# ---- is_hash_like_slug ----

def test_hash_like_pure_hex_12_chars():
    assert is_hash_like_slug("74f953b57f75") is True


def test_hash_like_pure_hex_16_chars():
    assert is_hash_like_slug("a1b2c3d4e5f60718") is True


def test_not_hash_like_username():
    assert is_hash_like_slug("local_user") is False


def test_not_hash_like_short_string_under_threshold():
    """Less than 8 chars is treated as non-hash by default."""
    assert is_hash_like_slug("rust") is False
    assert is_hash_like_slug("abc123") is False  # 6 chars, under threshold


def test_not_hash_like_mixed_with_underscores():
    """Slugs that look like 'account_a1b2c3d4' are mostly hash, but the
    underscore + 'account' prefix makes them human-readable."""
    assert is_hash_like_slug("account_a1b2c3d4") is False


def test_hash_like_long_hex_with_some_non_hex():
    """If 80%+ is hex AND length >= 8, still hash-like. 1 non-hex char in 16 hex chars = still hash-like."""
    assert is_hash_like_slug("74f953b57f75gh01") is True  # 14/16 = 87.5% hex


def test_not_hash_like_empty():
    assert is_hash_like_slug("") is False


# ---- display_name_for ----

def test_display_canonical_name_wins():
    """When canonical_name is present, use it regardless of entity_id."""
    canonical = {"74f953b57f75": "字节跳动"}
    assert display_name_for("74f953b57f75", canonical) == "字节跳动"


def test_display_slug_when_readable():
    """No canonical name, but slug is human-readable → use slug."""
    assert display_name_for("user:local_user", {}) == "local_user"
    assert display_name_for("topic:rust", {}) == "rust"


def test_display_unnamed_when_hash_slug():
    """No canonical name AND slug is hash-like → show '(未命名 organization)'."""
    assert display_name_for("organization:74f953b57f75", {}) == "(未命名 organization)"


def test_display_none_when_unparseable():
    """No canonical name, no parseable type → return None (caller drops)."""
    assert display_name_for("bare_hash_no_type", {}) is None
    assert display_name_for("", {}) is None


def test_display_account_prefix_keeps_slug():
    """presence:account_a1b2c3d4 — underscore-prefixed hash is treated as
    readable enough to show."""
    assert display_name_for("presence:account_a1b2c3d4", {}) == "account_a1b2c3d4"


def test_display_canonical_names_none_returns_slug_or_unnamed():
    """When canonical_names dict is None (legacy callers / None passed),
    the helper still works — falls straight to slug logic."""
    assert display_name_for("user:local_user", None) == "local_user"
    assert display_name_for("organization:74f953b57f75", None) == "(未命名 organization)"
