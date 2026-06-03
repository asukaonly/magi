"""SensorIngestionGateway ingress canonicalization (identity layer #5).

The gateway resolves a memory owner ``user_id`` from each
SensorOutput's provenance / domain_payload. Before identity-layer
hardening, a sensor could stash any string there and it would land
verbatim in memory L1 — a quiet bypass of the four formal ingress
sites. This test pins the contract that ``_resolve_memory_owner_user_id``
always returns a canonical ``MagiUserID`` value, no matter what the
sensor stuffed in.
"""
from __future__ import annotations

from magi.awareness.ingestion_gateway import SensorIngestionGateway
from magi.awareness.sensor_output import (
    ActivityFacet,
    SensorActivity,
    SensorNarration,
    SensorOutput,
)
from magi.identity import CANONICAL_LOCAL_USER


def _make_output(*, provenance: dict | None = None, domain_payload: dict | None = None) -> SensorOutput:
    return SensorOutput(
        source_type="test_sensor",
        source_item_id="item-1",
        occurred_at=1700000000.0,
        captured_at=1700000000.0,
        activity=SensorActivity(
            source=ActivityFacet(code="test", i18n_key="test"),
            action=ActivityFacet(code="observed", i18n_key="observed"),
        ),
        narration=SensorNarration(body="test event"),
        provenance=provenance or {},
        domain_payload=domain_payload or {},
    )


def test_canonicalizes_channel_prefixed_user_id_from_provenance():
    """Legacy or third-party sensor leaks ``channel_weixin_*`` →
    collapses to canonical local user, doesn't reach memory verbatim."""
    output = _make_output(
        provenance={"user_id": "channel_weixin_o9cq805VkoHSU8CcaDYe0iaJa-DM@im.wechat"},
    )
    assert (
        SensorIngestionGateway._resolve_memory_owner_user_id(output)
        == str(CANONICAL_LOCAL_USER)
    )


def test_canonicalizes_channel_prefixed_user_id_from_domain_payload():
    """Same coverage for domain_payload as for provenance — both are
    searched in order; both must be canonicalized."""
    output = _make_output(
        domain_payload={"memory_owner_user_id": "channel_telegram_42"},
    )
    assert (
        SensorIngestionGateway._resolve_memory_owner_user_id(output)
        == str(CANONICAL_LOCAL_USER)
    )


def test_empty_output_falls_back_to_canonical_local_user():
    """No user_id anywhere → canonical local user (single-user default).
    Matches the historical DEFAULT_USER_ID fallback semantics."""
    output = _make_output()
    assert (
        SensorIngestionGateway._resolve_memory_owner_user_id(output)
        == str(CANONICAL_LOCAL_USER)
    )


def test_canonical_user_id_passes_through_unchanged():
    """``"local_user"`` written directly into provenance must round-trip
    as canonical (single-user mode honors a canonical-shaped value)."""
    output = _make_output(provenance={"user_id": "local_user"})
    assert (
        SensorIngestionGateway._resolve_memory_owner_user_id(output)
        == str(CANONICAL_LOCAL_USER)
    )


def test_provenance_takes_precedence_over_domain_payload():
    """When BOTH containers have a user_id, provenance wins (the
    existing for-loop order). Pin so the order doesn't silently flip."""
    output = _make_output(
        provenance={"user_id": "alice"},
        domain_payload={"user_id": "bob"},
    )
    # alice is not channel-prefixed → single-user mode honors as-is.
    assert (
        SensorIngestionGateway._resolve_memory_owner_user_id(output) == "alice"
    )


def test_first_recognized_key_wins_within_container():
    """Inside one container, the for-loop tries memory_owner_user_id,
    then owner_user_id, then user_id — first non-empty wins."""
    output = _make_output(
        provenance={
            "user_id": "fallback",
            "owner_user_id": "second_choice",
            "memory_owner_user_id": "first_choice",
        },
    )
    assert (
        SensorIngestionGateway._resolve_memory_owner_user_id(output)
        == "first_choice"
    )
