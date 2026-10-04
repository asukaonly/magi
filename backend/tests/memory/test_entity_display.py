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

@pytest.mark.parametrize(
    "entity_id_input,expected_type,expected_identifier",
    [
        pytest.param("user:local_user", "user", "local_user", id="parse_user_local_user"),
        pytest.param("topic:rust", "topic", "rust", id="parse_topic_rust"),
        pytest.param(
            "organization:74f953b57f75", "organization", "74f953b57f75", id="parse_org_with_hash"
        ),
        pytest.param(
            "presence:account_a1b2c3d4",
            "presence",
            "account_a1b2c3d4",
            id="parse_presence_with_account_prefix",
        ),
    ],
)
def test_parse_entity_id_preserves_type_and_value(
    entity_id_input, expected_type, expected_identifier
):
    assert parse_entity_id(entity_id_input) == (expected_type, expected_identifier)


@pytest.mark.parametrize(
    "entity_id_input",
    [
        pytest.param("bare_hash_no_type", id="parse_no_colon_returns_none"),
        pytest.param("", id="parse_empty_returns_none"),
        pytest.param(":", id="parse_only_colon_returns_none"),
    ],
)
def test_parse_entity_id_rejects_missing_components(entity_id_input):
    assert parse_entity_id(entity_id_input) is None


def test_parse_multiple_colons_keeps_first_split():
    """Some entity_ids may have colons in the slug; only split on the first."""
    assert parse_entity_id("preference:address_form:子涵") == ("preference", "address_form:子涵")


# ---- is_hash_like_slug ----

@pytest.mark.parametrize(
    "expected_match,identifier",
    [
        pytest.param(True, "74f953b57f75", id="hash_like_pure_hex_12_chars"),
        pytest.param(True, "a1b2c3d4e5f60718", id="hash_like_pure_hex_16_chars"),
        pytest.param(False, "local_user", id="not_hash_like_username"),
        pytest.param(False, "account_a1b2c3d4", id="not_hash_like_mixed_with_underscores"),
        pytest.param(False, "", id="not_hash_like_empty"),
    ],
)
def test_hash_detection_distinguishes_names_from_hex_ids(expected_match, identifier):
    assert is_hash_like_slug(identifier) is expected_match


def test_not_hash_like_short_string_under_threshold():
    """Less than 8 chars is treated as non-hash by default."""
    assert is_hash_like_slug("rust") is False
    assert is_hash_like_slug("abc123") is False  # 6 chars, under threshold


def test_hash_like_long_hex_with_some_non_hex():
    """If 80%+ is hex AND length >= 8, still hash-like. 1 non-hex char in 16 hex chars = still hash-like."""
    assert is_hash_like_slug("74f953b57f75gh01") is True  # 14/16 = 87.5% hex


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
