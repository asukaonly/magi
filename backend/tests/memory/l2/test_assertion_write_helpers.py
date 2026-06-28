from __future__ import annotations

from typing import Any, Dict

from magi.memory.l2.assertions.write import (
    build_assertion_merge_context,
    normalize_assertion_candidate,
)


class _FakeAssertionHost:
    db_path = ":memory:"

    async def initialize(self) -> None:
        pass

    def _derive_trait_family(self, trait_name: str) -> str:
        return f"derived:{trait_name}"

    def _optional_text(self, value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None

    def _coerce_expires_at(
        self,
        value: Any,
        *,
        trait_family: str,
        trait_name: str,
        target_entity_id: str,
        anchor_at: float,
    ) -> float | None:
        if value == "ttl":
            return anchor_at + 60.0
        return None

    async def refresh_entity_snapshot(
        self,
        *,
        entity_id: str,
        entity_type: str | None = None,
    ) -> Dict[str, Any] | None:
        return None


def test_normalize_assertion_candidate_prepares_write_shape() -> None:
    normalized = normalize_assertion_candidate(
        {
            "entity_id": "user:u1",
            "entity_type": "unknown_type",
            "trait_family": "",
            "trait_name": "favorite_food",
            "trait_value": {"b": 2, "a": 1},
            "evidence_events": ["event: evt-2", "#evt-1"],
            "target_entity_type": "place",
            "target_entity_id": "entity:manner_coffee",
            "target_scope": " ",
            "temporal_scope": "",
            "decay_policy": " evidence_only ",
            "last_validated_at": 1234.0,
            "context_ref_id": " ctx-9 ",
            "expires_at": "ttl",
            "memory_subdomain": " profile ",
            "natural_summary": f"  {'x' * 520}  ",
        },
        _FakeAssertionHost(),
        now=2000.0,
    )

    assert normalized["entity_type"] == "other"
    assert normalized["trait_family"] == "derived:favorite_food"
    assert normalized["trait_value"] == '{"a": 1, "b": 2}'
    assert normalized["evidence_events"] == ["evt-2", "evt-1"]
    assert normalized["target_entity_type"] == "place"
    assert normalized["target_entity_id"] == "place:manner_coffee"
    assert normalized["target_scope"] == "global"
    assert normalized["temporal_scope"] == "session"
    assert normalized["decay_policy"] == "evidence_only"
    assert normalized["decay_anchor_at"] == 1234.0
    assert normalized["context_ref_id"] == "ctx-9"
    assert normalized["expires_at"] == 1294.0
    assert normalized["memory_subdomain"] == "profile"
    assert normalized["natural_summary"] == "x" * 500


def test_build_assertion_merge_context_identifies_authoritative_conflict() -> None:
    context = build_assertion_merge_context(
        {
            "trait_value": "rock",
            "temporal_scope": "stable",
            "evidence_events": '["evt-1", "evt-2"]',
            "first_inferred_at": 1000.0,
            "last_validated_at": 1500.0,
            "source_domain": "user_authored",
            "user_feedback": None,
        },
        {
            "trait_value": "jazz",
            "evidence_events": ["evt-2", "evt-3"],
            "first_inferred_at": 1200.0,
            "last_validated_at": 2000.0,
            "source_domain": "external_activity",
        },
    )

    assert context.existing_value == "rock"
    assert context.next_value == "jazz"
    assert context.merged_evidence == ["evt-1", "evt-2", "evt-3"]
    assert context.first_inferred_at == 1000.0
    assert context.last_validated_at == 2000.0
    assert context.existing_tier == "authoritative"
    assert context.candidate_tier == "inferred"
    assert context.value_changed is True
    assert context.inferred_conflicts_with_authoritative is True
    assert context.should_update_volatile_in_place is False
