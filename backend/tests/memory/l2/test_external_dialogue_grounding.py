"""Regression coverage for external dialogue speaker grounding."""

from __future__ import annotations

from magi.memory.l2.models import (
    L2EventWindow,
    L2EventWindowSummary,
    L2Phase1FactClaim,
    L2Phase1Result,
    L2Phase2AssertionCandidate,
    L2Phase2GraphEdge,
    L2Phase2Result,
)
from magi.memory.l2.pipeline.external_dialogue_grounding import (
    ground_phase1_external_dialogue_refs,
    ground_phase2_external_dialogue_refs,
)


def _event(event_id: str, speaker: str, text: str) -> dict[str, object]:
    return {
        "event_id": event_id,
        "content": f'DATE: 10:00 am on 27 June, 2023\n{speaker} said, "{text}"',
        "timestamp": 1687860000.0,
        "session_id": "session_1",
        "user_id": "benchmark/locomo/run/conv-26",
        "source": "benchmark.eval_support",
        "event_type": "BenchmarkExternalObservation",
        "author_type": "external",
    }


def _chrome_event() -> dict[str, object]:
    return {
        "event_id": "chrome-1",
        "content": "Chrome browse Tailscale - subnet routers",
        "timestamp": 1687860000.0,
        "source": "chrome_history",
        "event_type": "SensorObservation",
        "author_type": "external",
    }


def _window(*events: dict[str, object]) -> L2EventWindow:
    return L2EventWindow(
        events=list(events),
        summary=L2EventWindowSummary(
            event_count=len(events),
            session_id="session_1",
            user_id="benchmark/locomo/run/conv-26",
        ),
    )


def test_phase1_rewrites_external_dialogue_user_self_to_speaker() -> None:
    phase1 = L2Phase1Result(
        fact_claims=[
            L2Phase1FactClaim(
                subject_ref="user:self",
                subject_type="user",
                predicate="career_interest",
                object_ref="counseling and mental health",
                object_type="topic",
                evidence_text="I want to help people who have gone through the same things as me.",
                supporting_event_ids=["evt-caroline"],
            )
        ]
    )

    stats = ground_phase1_external_dialogue_refs(
        phase1,
        _window(_event("evt-caroline", "Caroline", "I want to work in counseling.")),
    )

    assert stats["rewritten_fact_claims"] == 1
    assert phase1.fact_claims[0].subject_ref == "person:caroline"
    assert phase1.fact_claims[0].subject_type == "person"
    assert any(entity.resolved_id == "person:caroline" for entity in phase1.entities)


def test_phase1_uses_supporting_event_ids_in_mixed_speaker_batch() -> None:
    phase1 = L2Phase1Result(
        fact_claims=[
            L2Phase1FactClaim(
                subject_ref="user:self",
                subject_type="user",
                predicate="bought",
                object_ref="running shoes",
                object_type="object",
                supporting_event_ids=["evt-melanie"],
            ),
            L2Phase1FactClaim(
                subject_ref="user:self",
                subject_type="user",
                predicate="joined",
                object_ref="support group",
                object_type="organization",
                supporting_event_ids=["evt-caroline"],
            ),
        ]
    )

    stats = ground_phase1_external_dialogue_refs(
        phase1,
        _window(
            _event("evt-caroline", "Caroline", "I joined a support group."),
            _event("evt-melanie", "Melanie", "I bought new running shoes."),
        ),
    )

    assert stats["rewritten_fact_claims"] == 2
    assert [claim.subject_ref for claim in phase1.fact_claims] == [
        "person:melanie",
        "person:caroline",
    ]


def test_phase1_drops_ambiguous_external_dialogue_user_self_in_mixed_batch() -> None:
    phase1 = L2Phase1Result(
        fact_claims=[
            L2Phase1FactClaim(
                subject_ref="user:self",
                subject_type="user",
                predicate="likes",
                object_ref="art",
                supporting_event_ids=[],
            )
        ]
    )

    stats = ground_phase1_external_dialogue_refs(
        phase1,
        _window(
            _event("evt-caroline", "Caroline", "I like abstract art."),
            _event("evt-melanie", "Melanie", "I like watercolor painting."),
        ),
    )

    assert stats["dropped_fact_claims"] == 1
    assert phase1.fact_claims == []


def test_phase1_leaves_non_dialogue_external_sensor_events_unchanged() -> None:
    phase1 = L2Phase1Result(
        fact_claims=[
            L2Phase1FactClaim(
                subject_ref="user:self",
                subject_type="user",
                predicate="visited",
                object_ref="Tailscale docs",
                supporting_event_ids=["chrome-1"],
            )
        ]
    )

    stats = ground_phase1_external_dialogue_refs(phase1, _window(_chrome_event()))

    assert stats["rewritten_fact_claims"] == 0
    assert stats["dropped_fact_claims"] == 0
    assert phase1.fact_claims[0].subject_ref == "user:self"


def test_phase2_rewrites_edges_and_assertions_to_external_dialogue_speaker() -> None:
    phase2 = L2Phase2Result(
        graph_edges=[
            L2Phase2GraphEdge(
                subject_ref="user:self",
                subject_type="user",
                predicate="career_interest",
                object_ref="counseling",
                supporting_event_ids=["evt-caroline"],
            )
        ],
        assertion_candidates=[
            L2Phase2AssertionCandidate(
                entity_ref="user:self",
                entity_type="user",
                trait_family="identity",
                trait_name="career_interest",
                trait_value="counseling",
                natural_summary="Caroline is interested in counseling work.",
                supporting_event_ids=["evt-caroline"],
            )
        ],
    )

    stats = ground_phase2_external_dialogue_refs(
        phase2,
        _window(_event("evt-caroline", "Caroline", "I want to work in counseling.")),
    )

    assert stats["rewritten_graph_edges"] == 1
    assert stats["rewritten_assertions"] == 1
    assert phase2.graph_edges[0].subject_ref == "person:caroline"
    assert phase2.graph_edges[0].subject_type == "person"
    assert phase2.assertion_candidates[0].entity_ref == "person:caroline"
    assert phase2.assertion_candidates[0].entity_type == "person"


def test_phase2_drops_ambiguous_external_dialogue_user_refs_in_mixed_batch() -> None:
    phase2 = L2Phase2Result(
        graph_edges=[
            L2Phase2GraphEdge(
                subject_ref="user:self",
                subject_type="user",
                predicate="owns",
                object_ref="painting",
                supporting_event_ids=[],
            )
        ],
        assertion_candidates=[
            L2Phase2AssertionCandidate(
                entity_ref="user:self",
                entity_type="user",
                trait_family="interest",
                trait_name="painting",
                trait_value="art",
                supporting_event_ids=[],
            )
        ],
    )

    stats = ground_phase2_external_dialogue_refs(
        phase2,
        _window(
            _event("evt-caroline", "Caroline", "I painted an abstract piece."),
            _event("evt-melanie", "Melanie", "I painted a watercolor piece."),
        ),
    )

    assert stats["dropped_graph_edges"] == 1
    assert stats["dropped_assertions"] == 1
    assert phase2.graph_edges == []
    assert phase2.assertion_candidates == []
