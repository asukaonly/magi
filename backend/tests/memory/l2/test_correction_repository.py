"""Tests for durable memory correction governance storage."""

from __future__ import annotations

import pytest

from magi.memory.l2.corrections.models import (
    CorrectionKind,
    CorrectionRule,
    CorrectionRuleKind,
    CorrectionTargetKind,
    NewMemoryCorrection,
)
from magi.memory.l2.corrections.repository import MemoryCorrectionRepository
from magi.memory.l2.corrections.request_identity import correction_request_fingerprint


def test_request_fingerprint_is_versioned_and_stable() -> None:
    first = correction_request_fingerprint(
        actor_id="local_user",
        target_kind=CorrectionTargetKind.ASSERTION,
        target_id="assertion-1",
        correction_kind=CorrectionKind.RECORD_ERROR,
        reason="Wrong city",
        replacement={"value": " Shanghai "},
        effective_at=None,
        scope=None,
        source_event_id=None,
    )
    second = correction_request_fingerprint(
        actor_id="local_user",
        target_kind=CorrectionTargetKind.ASSERTION,
        target_id="assertion-1",
        correction_kind=CorrectionKind.RECORD_ERROR,
        reason="Wrong city",
        replacement={"value": "Shanghai"},
        effective_at=None,
        scope={},
        source_event_id=None,
    )

    assert first.startswith("v1:")
    assert first == second


async def test_repository_creates_correction_rule_and_revision(
    l2_store_with_schema,
) -> None:
    repository = MemoryCorrectionRepository(l2_store_with_schema.db_path)
    correction = NewMemoryCorrection(
        correction_id="correction-1",
        request_id="request-1",
        actor_id="local_user",
        target_kind=CorrectionTargetKind.ASSERTION,
        target_id="assertion-1",
        slot_key="slot-1",
        claim_fingerprint="claim-1",
        correction_kind=CorrectionKind.RECORD_ERROR,
        before={"trait_value": "old"},
        request_fingerprint="fingerprint-1",
        reason="That is not true",
        created_at=100.0,
    )
    rule = CorrectionRule(
        rule_id="rule-1",
        correction_id=correction.correction_id,
        target_kind=CorrectionTargetKind.ASSERTION,
        rule_kind=CorrectionRuleKind.BLOCK_CLAIM,
        slot_key=correction.slot_key,
        claim_fingerprint=correction.claim_fingerprint,
        created_at=100.0,
    )

    result = await repository.create(
        correction,
        rules=[rule],
        subject_keys=["user:local_user"],
    )

    assert result.created is True
    assert result.correction.reason == "That is not true"
    assert result.correction.before == {"trait_value": "old"}
    assert result.subject_revisions == {"user:local_user": 1}
    assert await repository.current_subject_revision("user:local_user") == 1
    active_rules = await repository.list_active_rules(
        target_kind=CorrectionTargetKind.ASSERTION,
        slot_key="slot-1",
    )
    assert [(item["rule_kind"], item["claim_fingerprint"]) for item in active_rules] == [
        ("block_claim", "claim-1")
    ]


async def test_repository_request_id_is_idempotent(l2_store_with_schema) -> None:
    repository = MemoryCorrectionRepository(l2_store_with_schema.db_path)
    correction = NewMemoryCorrection(
        correction_id="correction-1",
        request_id="request-1",
        actor_id="local_user",
        target_kind=CorrectionTargetKind.EDGE,
        target_id="edge-1",
        slot_key="slot-1",
        claim_fingerprint="claim-1",
        correction_kind=CorrectionKind.RECORD_ERROR,
        before={"predicate": "LIKES"},
        request_fingerprint="fingerprint-1",
        created_at=100.0,
    )

    first = await repository.create(correction, subject_keys=["user:local_user"])
    second = await repository.create(
        NewMemoryCorrection(**{**correction.__dict__, "correction_id": "correction-2"}),
        subject_keys=["user:local_user"],
    )

    assert first.created is True
    assert second.created is False
    assert second.correction.correction_id == "correction-1"
    assert await repository.current_subject_revision("user:local_user") == 1

    with pytest.raises(ValueError, match="different correction"):
        await repository.create(
            NewMemoryCorrection(
                **{
                    **correction.__dict__,
                    "correction_id": "correction-3",
                    "request_fingerprint": "different-fingerprint",
                }
            ),
            subject_keys=["user:local_user"],
        )


async def test_repository_lists_target_history_newest_first(l2_store_with_schema) -> None:
    repository = MemoryCorrectionRepository(l2_store_with_schema.db_path)
    for number in (1, 2):
        await repository.create(
            NewMemoryCorrection(
                correction_id=f"correction-{number}",
                request_id=f"request-{number}",
                actor_id="local_user",
                target_kind=CorrectionTargetKind.ASSERTION,
                target_id="assertion-1",
                slot_key="slot-1",
                claim_fingerprint=f"claim-{number}",
                correction_kind=CorrectionKind.SITUATION_CHANGED,
                before={"trait_value": str(number)},
                request_fingerprint=f"fingerprint-{number}",
                created_at=float(number),
            )
        )

    history = await repository.list_for_target(
        target_kind=CorrectionTargetKind.ASSERTION,
        target_id="assertion-1",
    )

    assert [item.correction_id for item in history] == ["correction-2", "correction-1"]
