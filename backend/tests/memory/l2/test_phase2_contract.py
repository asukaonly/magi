from __future__ import annotations

from types import SimpleNamespace

from magi.memory.l2.phase1_models import L2Phase1FactClaim, L2Phase1Result
from magi.memory.l2.phase2_models import L2Phase2Result
from magi.memory.l2.pipeline.extraction_contracts import _Phase1ExtractionFlow
from magi.memory.l2.pipeline.phase2_flow import _validated_summary_by_key
from magi.memory.l2.semantic_routing import SemanticRouteInput, derive_semantic_route


def _flow(*claims: L2Phase1FactClaim) -> _Phase1ExtractionFlow:
    routes = {}
    for claim in claims:
        routes[claim.claim_id] = derive_semantic_route(
            SemanticRouteInput(
                claim_id=claim.claim_id,
                canonical_predicate=claim.predicate,
                fact_kind=str(claim.fact_kind),
                temporal_cue=claim.temporal_cue.value,
                subject_id=claim.subject_ref,
                subject_type=claim.subject_type,
                object_value=claim.object_ref,
                object_type=claim.object_type,
                object_entity_id=f"{claim.object_type}:{claim.object_ref.casefold()}",
                specificity=claim.specificity,
                raw_time_expression=claim.raw_time_expression,
                target_from=claim.target_from,
                target_to=claim.target_to,
                time_resolution="unscheduled",
                time_frame=claim.raw_time_frame,
            )
        )
    return _Phase1ExtractionFlow(
        phase1_result=L2Phase1Result(fact_claims=list(claims)),
        resolved_mentions=[],
        profile_signal_object_refs=set(),
        semantic_routes=routes,
        claim_outcomes=[],
    )


def _claim(claim_id: str, object_ref: str) -> L2Phase1FactClaim:
    return L2Phase1FactClaim(
        claim_id=claim_id,
        subject_ref="user:local_user",
        subject_type="user",
        predicate="LIKES",
        object_ref=object_ref,
        object_type="concept",
        fact_kind="stable_preference",
        temporal_cue="stable",
        evidence_text=f"我喜欢{object_ref}",
        supporting_event_ids=[f"evt_{claim_id}"],
    )


def test_phase2_result_normalizes_summaries() -> None:
    result = L2Phase2Result.from_dict(
        {
            "summaries": [{"claim_ids": ["clm_1", "clm_1"], "text": "  我喜欢咖啡。 "}],
        }
    )

    assert result.to_dict() == {
        "summaries": [{"claim_ids": ["clm_1"], "text": "我喜欢咖啡。"}]
    }


def test_summary_must_use_known_claims_from_one_materialization_target() -> None:
    coffee = _claim("clm_coffee", "咖啡")
    music = _claim("clm_music", "纯音乐")
    flow = _flow(coffee, music)
    result = L2Phase2Result.from_dict(
        {
            "summaries": [
                {"claim_ids": ["clm_coffee"], "text": "用户喜欢咖啡。"},
                {"claim_ids": ["clm_coffee", "clm_music"], "text": "用户有一些偏好。"},
                {"claim_ids": ["clm_unknown"], "text": "未知 Claim。"},
            ]
        }
    )

    accepted, rejected = _validated_summary_by_key(flow, result)

    assert len(accepted) == 1
    assert next(iter(accepted.values())) == "用户喜欢咖啡。"
    assert rejected == 2


def test_summary_requires_a_grounded_object_anchor() -> None:
    flow = _flow(_claim("clm_coffee", "咖啡"))
    result = SimpleNamespace(
        summaries=[SimpleNamespace(claim_ids=["clm_coffee"], text="用户有一种饮品偏好。")]
    )

    accepted, rejected = _validated_summary_by_key(flow, result)

    assert accepted == {}
    assert rejected == 1
