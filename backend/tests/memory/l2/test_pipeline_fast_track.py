from __future__ import annotations

from types import SimpleNamespace

from magi.memory.event_contracts import MemoryDomain, TomDepth
from magi.memory.l2.extraction_profiles import ExtractionProfile
from magi.memory.l2.models import (
    L2Phase1Entity,
    L2Phase1FactClaim,
    L2Phase1Result,
    ResolvedEntityMention,
)
from magi.memory.l2.pipeline.validation.graph_fast_track import L2GraphFastTrackMixin


class _FastTrackHarness(L2GraphFastTrackMixin):
    def _normalize_predicate(self, raw_value: object) -> str | None:
        text = str(raw_value or "").strip().upper()
        return text or None

    def _normalize_entity_type(self, raw_value: object) -> str | None:
        text = str(raw_value or "").strip().lower()
        return text or None

    def _resolve_phase2_object_id(
        self,
        *,
        raw_object_ref: object,
        object_type: str | None,
        resolved_mentions: list[ResolvedEntityMention],
        catalog_name_index: dict[str, str] | None = None,
    ) -> str | None:
        _ = (object_type, catalog_name_index)
        raw_text = str(raw_object_ref or "").strip()
        for mention in resolved_mentions:
            if raw_text in {
                mention.mention_text,
                mention.normalized_surface,
                mention.resolved_entity_id,
            }:
                return mention.resolved_entity_id
        return raw_text if ":" in raw_text else None

    def _resolve_phase2_subject_id(self, *, event: object, subject_ref: object) -> str | None:
        _ = event
        return str(subject_ref or "").strip() or None

    def _should_reject_preference_graph_candidate(self, **kwargs: object) -> bool:
        _ = kwargs
        return False

    def _non_empty_text(self, value: object) -> str | None:
        return str(value or "").strip() or None


def test_graph_fast_track_uses_effective_assertion_permission() -> None:
    phase1_result = L2Phase1Result(
        entities=[
            L2Phase1Entity(
                surface="诡秘之主",
                normalized_name="诡秘之主",
                entity_type="media",
                is_new=True,
                confidence=0.95,
            )
        ],
        fact_claims=[
            L2Phase1FactClaim(
                subject_ref="user:self",
                subject_type="user",
                predicate="VIEWED",
                object_ref="诡秘之主",
                object_type="media",
                fact_kind="explicit_fact",
                confidence=0.8,
            )
        ],
    )
    resolved_mentions = [
        ResolvedEntityMention(
            mention_text="诡秘之主",
            normalized_surface="诡秘之主",
            entity_type="media",
            resolved_entity_id="media:lord-of-the-mysteries",
            confidence=0.95,
        )
    ]
    profile = ExtractionProfile(
        profile_id="source.chrome_history",
        allowed_entity_types=frozenset({"media"}),
        allowed_predicates=frozenset({"VIEWED"}),
        structured_allowed_entity_types=frozenset({"media"}),
        structured_allowed_predicates=frozenset({"VIEWED"}),
        allow_graph=True,
        allow_assertion=False,
    )
    policy = SimpleNamespace(allow_assertion_write=True)

    assert _FastTrackHarness()._can_fast_track(
        phase1_result=phase1_result,
        resolved_mentions=resolved_mentions,
        existing_graph_edges=[],
        profile=profile,
        policy=policy,
    ) is True


def test_graph_fast_track_blocks_when_assertions_are_effectively_allowed() -> None:
    phase1_result = L2Phase1Result(
        fact_claims=[
            L2Phase1FactClaim(
                predicate="VIEWED",
                object_ref="media:lord-of-the-mysteries",
                object_type="media",
                fact_kind="explicit_fact",
                confidence=0.8,
            )
        ]
    )
    profile = ExtractionProfile(
        profile_id="chat.user_message",
        allowed_entity_types=frozenset({"media"}),
        allowed_predicates=frozenset({"VIEWED"}),
        structured_allowed_entity_types=frozenset({"media"}),
        structured_allowed_predicates=frozenset({"VIEWED"}),
        allow_graph=True,
        allow_assertion=True,
    )
    policy = SimpleNamespace(allow_assertion_write=True)

    assert _FastTrackHarness()._can_fast_track(
        phase1_result=phase1_result,
        resolved_mentions=[],
        existing_graph_edges=[],
        profile=profile,
        policy=policy,
    ) is False


def test_graph_fast_track_rejects_claim_without_grounded_event_ids() -> None:
    event = SimpleNamespace(
        event_id="evt-current",
        timestamp=1_700_000_000.0,
        source="chat",
        user_id="u1",
        memory_domain=MemoryDomain.USER_AUTHORED,
        tom_depth=TomDepth.TOPOLOGY_ONLY,
    )
    profile = ExtractionProfile(
        profile_id="chat.user_message",
        allowed_entity_types=frozenset({"group"}),
        allowed_predicates=frozenset({"LIKES"}),
        structured_allowed_entity_types=frozenset({"group"}),
        structured_allowed_predicates=frozenset({"LIKES"}),
        allow_graph=True,
        allow_assertion=False,
    )
    phase1_result = L2Phase1Result(
        fact_claims=[
            L2Phase1FactClaim(
                subject_ref="user:u1",
                predicate="LIKES",
                object_ref="group:diiv",
                object_type="group",
                evidence_text="我喜欢 DIIV",
            )
        ]
    )

    candidates = _FastTrackHarness()._fast_track_claims_to_candidates(
        phase1_result=phase1_result,
        event=event,
        evidence_event_ids=["evt-current"],
        resolved_mentions=[],
        profile=profile,
    )

    assert candidates == []
