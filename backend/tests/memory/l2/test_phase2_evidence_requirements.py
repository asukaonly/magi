"""Tests that Phase 2 cannot expand missing support to a whole batch."""

from types import SimpleNamespace
from typing import Any

from magi.memory.event_contracts import MemoryDomain, TomDepth
from magi.memory.l2.models import L2Phase2AssertionCandidate, L2Phase2GraphEdge
from magi.memory.l2.pipeline.validation.assertions import L2AssertionValidationMixin
from magi.memory.l2.pipeline.validation.graph_phase2 import L2Phase2GraphValidationMixin


def _event() -> SimpleNamespace:
    return SimpleNamespace(
        event_id="evt-current",
        timestamp=1_700_000_000.0,
        source="chat",
        user_id="u1",
        memory_domain=MemoryDomain.USER_AUTHORED,
        tom_depth=TomDepth.TOPOLOGY_ONLY,
    )


class _GraphHarness(L2Phase2GraphValidationMixin):
    def _normalize_predicate(self, raw_value: object) -> str | None:
        return str(raw_value or "").strip().upper() or None

    def _normalize_entity_type(self, raw_value: object) -> str | None:
        return str(raw_value or "").strip().casefold() or None

    def _resolve_phase2_subject_id(self, *, event: object, subject_ref: object) -> str | None:
        _ = event
        return str(subject_ref or "").strip() or None

    def _resolve_phase2_object_id(self, **kwargs: object) -> str | None:
        return str(kwargs.get("raw_object_ref") or "").strip() or None

    def _normalize_profile_signal_value(self, value: object) -> str | None:
        return str(value or "").strip().casefold() or None

    def _should_reject_preference_graph_candidate(self, **kwargs: object) -> bool:
        _ = kwargs
        return False

    def _non_empty_text(self, value: object) -> str | None:
        return str(value or "").strip() or None


class _AssertionHarness(L2AssertionValidationMixin):
    def _resolve_self_entity_id(self, event: object) -> str:
        _ = event
        return "user:u1"

    def _non_empty_text(self, value: Any) -> str | None:
        return str(value or "").strip() or None

    def _normalize_entity_type(self, raw_value: Any) -> str | None:
        return str(raw_value or "").strip().casefold() or None


def test_phase2_graph_edge_without_support_is_rejected() -> None:
    profile = SimpleNamespace(
        allow_graph=True,
        effective_structured_allowed_entity_types=frozenset({"group"}),
        effective_structured_allowed_predicates=frozenset({"LIKES"}),
    )
    policy = SimpleNamespace(allow_graph_write=True, graph_scope="full")

    prepared, corroborations, rejected = _GraphHarness()._validate_phase2_graph_edges(
        event=_event(),
        profile=profile,
        policy=policy,
        resolved_mentions=[],
        evidence_event_ids=["evt-current", "evt-other"],
        phase2_edges=[
            L2Phase2GraphEdge(
                subject_ref="user:u1",
                predicate="LIKES",
                object_ref="group:diiv",
                object_type="group",
                evidence_text="我喜欢 DIIV",
            )
        ],
    )

    assert prepared == []
    assert corroborations == []
    assert rejected == 1


def test_phase2_assertion_without_support_is_rejected() -> None:
    profile = SimpleNamespace(
        allow_assertion=True,
        assertion_mode="phase2_candidate",
        allowed_assertion_families=frozenset({"preference_profile"}),
        allowed_assertion_traits="all",
    )
    policy = SimpleNamespace(allow_assertion_write=True, assertion_scope="full")

    prepared, rejected = _AssertionHarness()._validate_phase2_assertions(
        event=_event(),
        profile=profile,
        policy=policy,
        graph_candidates=[],
        default_event_ids=["evt-current", "evt-other"],
        phase2_assertions=[
            L2Phase2AssertionCandidate(
                entity_ref="user:u1",
                trait_family="preference_profile",
                trait_name="interest.music",
                trait_value="DIIV",
                natural_summary="喜欢 DIIV",
            )
        ],
    )

    assert prepared == []
    assert rejected == 1
