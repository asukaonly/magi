"""Tests for deterministic Phase 1 claim projection into the graph."""

from types import SimpleNamespace

from magi.memory.l2.extraction_profiles import ExtractionProfile
from magi.memory.l2.models import L2Phase1FactClaim, L2Phase1Result, ResolvedEntityMention
from magi.memory.l2.pipeline.validation.phase1_graph import L2Phase1GraphProjectionMixin


class _ProjectionHarness(L2Phase1GraphProjectionMixin):
    def _normalize_predicate(self, raw_value: object) -> str | None:
        return str(raw_value or "").strip().upper() or None

    def _normalize_entity_type(self, raw_value: object) -> str | None:
        return str(raw_value or "").strip().casefold() or None

    def _resolve_phase2_subject_id(self, *, event: object, subject_ref: object) -> str | None:
        _ = event
        return str(subject_ref or "").strip() or None

    def _resolve_phase2_object_id(
        self,
        *,
        raw_object_ref: object,
        object_type: str | None,
        resolved_mentions: list[ResolvedEntityMention],
        catalog_name_index: dict[str, str] | None = None,
    ) -> str | None:
        _ = (object_type, resolved_mentions, catalog_name_index)
        value = str(raw_object_ref or "").strip()
        return value if ":" in value else None

    def _should_reject_preference_graph_candidate(self, **kwargs: object) -> bool:
        _ = kwargs
        return False

    def _non_empty_text(self, value: object) -> str | None:
        return str(value or "").strip() or None


def _profile(*, allow_assertion: bool = True) -> ExtractionProfile:
    return ExtractionProfile(
        profile_id="chat.user_message",
        allowed_entity_types=frozenset({"group"}),
        allowed_predicates=frozenset({"LIKES"}),
        structured_allowed_entity_types=frozenset({"group"}),
        structured_allowed_predicates=frozenset({"LIKES"}),
        allow_graph=True,
        allow_assertion=allow_assertion,
    )


def test_phase1_claim_projects_directly_to_graph_candidate() -> None:
    claim = L2Phase1FactClaim(
        claim_id="claim:diiv",
        subject_ref="user:u1",
        predicate="LIKES",
        object_ref="group:diiv",
        object_type="group",
        fact_kind="stable_preference",
        evidence_text="我喜欢 DIIV",
        supporting_event_ids=["evt-diiv"],
        confidence=0.8,
        fact_valid_from=1_699_900_000.0,
        fact_valid_to=1_700_100_000.0,
        target_from=1_800_000_000.0,
        target_to=1_800_100_000.0,
    )

    candidates, outcomes = _ProjectionHarness()._project_phase1_graph_candidates(
        phase1_result=L2Phase1Result(fact_claims=[claim]),
        event=SimpleNamespace(timestamp=1_700_000_000.0, source="chat"),
        evidence_event_ids=["evt-diiv"],
        resolved_mentions=[],
        profile=_profile(),
    )

    assert outcomes == []
    assert candidates == [
        {
            "_claim_id": "claim:diiv",
            "subject_id": "user:u1",
            "subject_type": "user",
            "predicate": "LIKES",
            "object_id": "group:diiv",
            "object_type": "group",
            "fact_kind": "stable_preference",
            "evidence_event_ids": ["evt-diiv"],
            "confidence": 0.8,
            "observed_at": 1_700_000_000.0,
            "source_type": "chat",
            "extraction_method": "llm_phase1_grounded",
            "evidence_text": "我喜欢 DIIV",
            "evidence_class": None,
            "valid_from": 1_699_900_000.0,
            "valid_to": 1_700_100_000.0,
        }
    ]


def test_future_plan_is_assertion_only_and_never_uses_target_window_as_fact_validity() -> None:
    claim = L2Phase1FactClaim(
        claim_id="claim:goal",
        subject_ref="user:u1",
        predicate="PLANS_TO",
        object_ref="activity:beach-trip",
        object_type="activity",
        fact_kind="future_intent",
        evidence_text="我明天去海边",
        supporting_event_ids=["evt-goal"],
        target_from=1_800_000_000.0,
        target_to=1_800_086_400.0,
    )
    profile = ExtractionProfile(
        profile_id="chat.user_message",
        allowed_entity_types=frozenset({"activity"}),
        allowed_predicates=frozenset({"PLANS_TO"}),
        structured_allowed_entity_types=frozenset({"activity"}),
        structured_allowed_predicates=frozenset({"PLANS_TO"}),
    )

    candidates, outcomes = _ProjectionHarness()._project_phase1_graph_candidates(
        phase1_result=L2Phase1Result(fact_claims=[claim]),
        event=SimpleNamespace(timestamp=1_700_000_000.0, source="chat"),
        evidence_event_ids=["evt-goal"],
        resolved_mentions=[],
        profile=profile,
    )

    assert candidates == []
    assert len(outcomes) == 1
    assert outcomes[0].outcome == "skipped"
    assert outcomes[0].reason_code == "goal_assertion_only"


def test_phase1_graph_projection_rejects_missing_support() -> None:
    claim = L2Phase1FactClaim(
        claim_id="claim:diiv",
        subject_ref="user:u1",
        predicate="LIKES",
        object_ref="group:diiv",
        object_type="group",
    )

    candidates, outcomes = _ProjectionHarness()._project_phase1_graph_candidates(
        phase1_result=L2Phase1Result(fact_claims=[claim]),
        event=SimpleNamespace(timestamp=1_700_000_000.0, source="chat"),
        evidence_event_ids=["evt-diiv"],
        resolved_mentions=[],
        profile=_profile(),
    )

    assert candidates == []
    assert len(outcomes) == 1
    assert outcomes[0].outcome == "rejected"
    assert outcomes[0].reason_code == "missing_grounded_support"
    assert outcomes[0].claim_id == "claim:diiv"
