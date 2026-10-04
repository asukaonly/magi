"""SourceIngestionGateway ingress canonicalization (identity layer #5).

The gateway resolves a memory owner ``user_id`` from each
SourceOutput's provenance / domain_payload. Before identity-layer
hardening, a source could stash any string there and it would land
verbatim in memory L1 — a quiet bypass of the four formal ingress
sites. This test pins the contract that ``_resolve_memory_owner_user_id``
always returns a canonical ``MagiUserID`` value, no matter what the
source stuffed in.
"""
from __future__ import annotations

import pytest

from magi.awareness.ingestion_gateway import SourceIngestionGateway
from magi.awareness.source_output import (
    ActivityFacet,
    SourceActivity,
    SourceNarration,
    SourceOutput,
)
from magi.identity import CANONICAL_LOCAL_USER


def _make_output(*, provenance: dict | None = None, domain_payload: dict | None = None) -> SourceOutput:
    return SourceOutput(
        source_type="test_source",
        source_item_id="item-1",
        occurred_at=1700000000.0,
        captured_at=1700000000.0,
        activity=SourceActivity(
            source=ActivityFacet(code="test", i18n_key="test"),
            action=ActivityFacet(code="observed", i18n_key="observed"),
        ),
        narration=SourceNarration(body="test event"),
        provenance=provenance or {},
        domain_payload=domain_payload or {},
    )


@pytest.mark.parametrize(
    "provenance,domain_payload,expected",
    [
        (
            {"user_id": "channel_weixin_o9cq805VkoHSU8CcaDYe0iaJa-DM@im.wechat"},
            {},
            str(CANONICAL_LOCAL_USER),
        ),
        ({"user_id": "local_user"}, {}, str(CANONICAL_LOCAL_USER)),
        ({}, {"memory_owner_user_id": "channel_telegram_42"}, str(CANONICAL_LOCAL_USER)),
        ({}, {}, str(CANONICAL_LOCAL_USER)),
        ({"user_id": "alice"}, {"user_id": "bob"}, "alice"),
        (
            {
                "user_id": "fallback",
                "owner_user_id": "second_choice",
                "memory_owner_user_id": "first_choice",
            },
            {},
            "first_choice",
        ),
        (
            {},
            {
                "user_id": "fallback",
                "owner_user_id": "second_choice",
                "memory_owner_user_id": "first_choice",
            },
            "first_choice",
        ),
    ],
)
def test_source_identity_precedence_and_canonicalization(provenance, domain_payload, expected):
    output = _make_output(provenance=provenance, domain_payload=domain_payload)
    assert SourceIngestionGateway._resolve_memory_owner_user_id(output) == expected
