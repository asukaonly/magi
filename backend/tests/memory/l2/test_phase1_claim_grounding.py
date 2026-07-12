"""Tests for deterministic Phase 1 claim evidence grounding."""

from magi.memory.l2.models import (
    L2BatchEvent,
    L2EventWindow,
    L2Phase1FactClaim,
    L2Phase1Result,
)
from magi.memory.l2.pipeline.claim_grounding import ground_phase1_fact_claims


def _window(*events: tuple[str, str]) -> L2EventWindow:
    return L2EventWindow(
        events=[
            L2BatchEvent(event_id=event_id, content=content)
            for event_id, content in events
        ]
    )


def _claim(**overrides: object) -> L2Phase1FactClaim:
    payload: dict[str, object] = {
        "subject_ref": "user:self",
        "predicate": "LIKES",
        "object_ref": "DIIV",
        "object_type": "group",
        "evidence_text": "我很喜欢 DIIV",
        "supporting_event_ids": [],
    }
    payload.update(overrides)
    return L2Phase1FactClaim.from_dict(payload)


def test_ground_phase1_claim_binds_quote_to_exact_event() -> None:
    result = L2Phase1Result(
        fact_claims=[_claim(supporting_event_ids=["evt-wrong", "evt-outside"])]
    )

    stats = ground_phase1_fact_claims(
        result,
        _window(
            ("evt-a", "昨晚去看了 DIIV 演出，我很喜欢 DIIV。"),
            ("evt-b", "今天修复了项目里的测试。"),
        ),
    )

    assert stats == {"kept": 1, "rejected": 0, "rebound": 1}
    assert result.fact_claims[0].supporting_event_ids == ["evt-a"]
    assert result.fact_claims[0].claim_id.startswith("claim:")


def test_ground_phase1_claim_rejects_ungrounded_multi_event_claim() -> None:
    result = L2Phase1Result(
        fact_claims=[
            _claim(
                evidence_text="",
                supporting_event_ids=["evt-a", "evt-outside"],
            )
        ]
    )

    stats = ground_phase1_fact_claims(
        result,
        _window(
            ("evt-a", "昨晚去看了 DIIV 演出。"),
            ("evt-b", "今天修复了项目里的测试。"),
        ),
    )

    assert stats == {"kept": 0, "rejected": 1, "rebound": 0}
    assert result.fact_claims == []


def test_ground_phase1_claim_allows_single_event_as_exact_evidence() -> None:
    result = L2Phase1Result(
        fact_claims=[
            _claim(
                evidence_text="",
                supporting_event_ids=["evt-only"],
            )
        ]
    )

    stats = ground_phase1_fact_claims(
        result,
        _window(("evt-only", "昨晚去看了 DIIV 演出。")),
    )

    assert stats == {"kept": 1, "rejected": 0, "rebound": 0}
    assert result.fact_claims[0].supporting_event_ids == ["evt-only"]


def test_ground_phase1_claim_ids_are_deterministic_and_claim_specific() -> None:
    first = _claim()
    second = _claim(predicate="ATTENDED", evidence_text="去看了 DIIV 演出")
    window = _window(("evt-a", "我很喜欢 DIIV，昨晚去看了 DIIV 演出。"))

    first_result = L2Phase1Result(fact_claims=[first, second])
    ground_phase1_fact_claims(first_result, window)
    first_ids = [claim.claim_id for claim in first_result.fact_claims]

    replay_result = L2Phase1Result(fact_claims=[_claim(), _claim(
        predicate="ATTENDED",
        evidence_text="去看了 DIIV 演出",
    )])
    ground_phase1_fact_claims(replay_result, window)

    assert first_ids == [claim.claim_id for claim in replay_result.fact_claims]
    assert len(set(first_ids)) == 2
