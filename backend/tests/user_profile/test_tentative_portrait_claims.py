"""Contracts for tentative, Claim-backed self-report portrait lines."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import pytest

from _shared.memory_schema import apply_memory_shared_schema
from magi.memory.l2.store import L2CognitionStore
from magi.memory.l2.semantic_routing import ROUTE_CONTRACT_VERSION
from magi.user_profile.portrait_claim_query import list_tentative_portrait_claims
from magi.user_profile.portrait_projection_builder import UserPortraitProjectionBuilder
from magi.user_profile.portrait_projection_freshness import portrait_projection_is_stale
from magi.user_profile.portrait_signal_policy import (
    classify_tentative_portrait_claim,
    tentative_portrait_prompt_line,
)


def _route_details(
    *,
    family: str,
    trait_code: str,
    value_fingerprint: str,
    natural_summary: str = "",
) -> dict[str, Any]:
    return {
        "semantic_route_id": f"{family}:{trait_code}",
        "family": family,
        "trait_code": trait_code,
        "object_role": "canonical_value",
        "value_fingerprint": value_fingerprint,
        "target_entity_type": None,
        "scope_key": "global",
        "natural_summary": natural_summary,
    }


def _seed_claim(
    db_path: str,
    *,
    claim_id: str,
    event_id: str,
    predicate: str,
    object_value: Any,
    family: str,
    trait_code: str,
    slot_key: str,
    value_fingerprint: str,
    created_at: float,
    author_type: str = "user",
    evidence_class: str = "user_self_report",
    availability: str = "active",
    fact_kind: str = "explicit_fact",
    fact_valid_from: float | None = None,
    fact_valid_to: float | None = None,
    natural_summary: str = "",
) -> None:
    with sqlite3.connect(db_path) as db:
        db.execute(
            """
            INSERT INTO l2_grounded_claims(
                claim_id, identity_key, extractor_contract_version,
                evidence_rule_version, origin_attempt_key, profile_id, user_id,
                subject_ref, subject_type, canonical_predicate, fact_kind,
                object_type, polarity, specificity, confidence,
                object_value_json, object_surface, temporal_cue,
                fact_valid_from, fact_valid_to, availability, created_at, updated_at
            ) VALUES (?, ?, 1, 1, ?, 'default', 'local_user',
                      'user:local_user', 'user', ?, ?, 'topic', 'positive',
                      'concrete', 0.9, ?, ?, 'stable', ?, ?, ?, ?, ?)
            """,
            (
                claim_id,
                f"identity:{claim_id}",
                f"attempt:{claim_id}",
                predicate,
                fact_kind,
                json.dumps(object_value, ensure_ascii=False),
                str(object_value),
                fact_valid_from,
                fact_valid_to,
                availability,
                created_at,
                created_at,
            ),
        )
        db.execute(
            """
            INSERT INTO l2_claim_evidence(
                claim_id, event_id, link_role, required_for_grounding,
                event_time, timestamp_confidence, timestamp_quality,
                evidence_rule_version, evidence_mode, source_type,
                source_domain, author_type, evidence_class, created_at
            ) VALUES (?, ?, 'supporting', 0, ?, 'exact', 'exact', 1,
                      'direct', 'chat', 'user_authored', ?, ?, ?)
            """,
            (
                claim_id,
                event_id,
                created_at,
                author_type,
                evidence_class,
                created_at,
            ),
        )
        _seed_route_outcome(
            db,
            claim_id=claim_id,
            outcome_id=f"route:{claim_id}:1",
            outcome="routed",
            family=family,
            trait_code=trait_code,
            slot_key=slot_key,
            value_fingerprint=value_fingerprint,
            created_at=created_at,
            natural_summary=natural_summary,
        )
        db.commit()


def _seed_route_outcome(
    db: sqlite3.Connection,
    *,
    claim_id: str,
    outcome_id: str,
    outcome: str,
    family: str,
    trait_code: str,
    slot_key: str,
    value_fingerprint: str,
    created_at: float,
    natural_summary: str = "",
) -> None:
    db.execute(
        """
        INSERT INTO l2_claim_projection_outcomes(
            outcome_id, claim_id, attempt_key, target_kind, target_id,
            target_slot_key, route_contract_version, outcome, reason_code,
            details_json, created_at
        ) VALUES (?, ?, ?, 'route', ?, ?, ?, ?, 'route_supported', ?, ?)
        """,
        (
            outcome_id,
            claim_id,
            f"attempt:{outcome_id}",
            f"route:{claim_id}",
            slot_key,
            ROUTE_CONTRACT_VERSION,
            outcome,
            json.dumps(
                _route_details(
                    family=family,
                    trait_code=trait_code,
                    value_fingerprint=value_fingerprint,
                    natural_summary=natural_summary,
                ),
                ensure_ascii=False,
            ),
            created_at,
        ),
    )


def _seed_assertion_outcome(
    db_path: str,
    *,
    claim_id: str,
    assertion_id: str,
    created_at: float,
) -> None:
    with sqlite3.connect(db_path) as db:
        db.execute(
            """
            INSERT INTO l2_claim_projection_outcomes(
                outcome_id, claim_id, attempt_key, target_kind, target_id,
                target_slot_key, route_contract_version, outcome, created_at
            ) VALUES (?, ?, ?, 'assertion', ?, NULL, ?, 'projected', ?)
            """,
            (
                f"assertion:{claim_id}:{assertion_id}",
                claim_id,
                f"attempt:assertion:{claim_id}",
                assertion_id,
                ROUTE_CONTRACT_VERSION,
                created_at,
            ),
        )
        db.commit()


def _store(db_path: str, *, visible_event_ids: set[str]) -> L2CognitionStore:
    async def resolve(event_ids: list[str]) -> dict[str, float]:
        return {
            event_id: 1_700_000_000.0
            for event_id in event_ids
            if event_id in visible_event_ids
        }

    return L2CognitionStore(
        db_path=db_path,
        evidence_timestamp_resolver=resolve,
    )


@pytest.mark.parametrize(
    ("predicate", "family", "trait_code", "value", "expected"),
    [
        ("LIKES", "preference_profile", "preference.affinity", "纯音乐", "喜欢「纯音乐」"),
        (
            "DISLIKES",
            "preference_profile",
            "preference.affinity",
            "嘈杂环境",
            "不喜欢「嘈杂环境」",
        ),
        (
            "INTERESTED_IN",
            "interest_profile",
            "interest.attention",
            "本地 AI",
            "对「本地 AI」感兴趣",
        ),
        ("REAL_NAME", "identity_profile", "identity.real_name", "明日香", "真实姓名是「明日香」"),
        (
            "PREFERRED_COMMUNICATION_STYLE",
            "communication_profile",
            "communication.response_style.preferred",
            "先讲结论",
            "偏好的沟通方式是「先讲结论」",
        ),
    ],
)
def test_tentative_claim_renderer_uses_only_typed_claim_and_route_fields(
    predicate: str,
    family: str,
    trait_code: str,
    value: str,
    expected: str,
) -> None:
    decision = classify_tentative_portrait_claim(
        {
            "availability": "active",
            "canonical_predicate": predicate,
            "object_value": value,
        },
        {
            "target_kind": "route",
            "target_slot_key": "slt_contract",
            "route_contract_version": ROUTE_CONTRACT_VERSION,
            "outcome": "routed",
            "details": _route_details(
                family=family,
                trait_code=trait_code,
                value_fingerprint="val_contract",
                natural_summary="不要采用这段不一致的模型摘要",
            ),
        },
    )

    assert decision is not None
    assert decision.statement == expected
    assert tentative_portrait_prompt_line(decision.statement) == (
        f"用户曾自述：{expected}（尚未形成长期结论）"
    )
    assert "模型摘要" not in decision.statement


def test_tentative_claim_policy_rejects_non_profile_and_stale_routes() -> None:
    claim = {
        "availability": "active",
        "canonical_predicate": "WORKS_ON",
        "object_value": "Magi",
    }
    project_route = {
        "target_kind": "route",
        "target_slot_key": "slt_project",
        "route_contract_version": ROUTE_CONTRACT_VERSION,
        "outcome": "routed",
        "details": _route_details(
            family="project_profile",
            trait_code="project.engagement.active",
            value_fingerprint="val_project",
        ),
    }
    stale_route = {
        **project_route,
        "route_contract_version": 0,
        "details": _route_details(
            family="preference_profile",
            trait_code="preference.affinity",
            value_fingerprint="val_stale",
        ),
    }

    assert classify_tentative_portrait_claim(claim, project_route) is None
    assert classify_tentative_portrait_claim(
        {
            "availability": "active",
            "canonical_predicate": "LIKES",
            "object_value": "Magi",
        },
        stale_route,
    ) is None


@pytest.mark.asyncio
async def test_builder_limits_visible_self_reports_and_preserves_them_from_llm_override(
    tmp_path,
) -> None:
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    _seed_claim(
        db_path,
        claim_id="claim-like",
        event_id="event-like",
        predicate="LIKES",
        object_value="没有人声的音乐",
        family="preference_profile",
        trait_code="preference.affinity",
        slot_key="slt_like",
        value_fingerprint="val_like",
        created_at=300.0,
        natural_summary="用户讨厌所有音乐",
    )
    _seed_claim(
        db_path,
        claim_id="claim-style",
        event_id="event-style",
        predicate="PREFERRED_COMMUNICATION_STYLE",
        object_value="先讲结论",
        family="communication_profile",
        trait_code="communication.response_style.preferred",
        slot_key="slt_style",
        value_fingerprint="val_style",
        created_at=290.0,
    )
    _seed_claim(
        db_path,
        claim_id="claim-third",
        event_id="event-third",
        predicate="REAL_NAME",
        object_value="明日香",
        family="identity_profile",
        trait_code="identity.real_name",
        slot_key="slt_name",
        value_fingerprint="val_name",
        created_at=280.0,
    )
    _seed_claim(
        db_path,
        claim_id="claim-hidden",
        event_id="event-hidden",
        predicate="LIKES",
        object_value="不可见内容",
        family="preference_profile",
        trait_code="preference.affinity",
        slot_key="slt_hidden",
        value_fingerprint="val_hidden",
        created_at=400.0,
    )
    _seed_claim(
        db_path,
        claim_id="claim-passive",
        event_id="event-passive",
        predicate="LIKES",
        object_value="被动观察内容",
        family="preference_profile",
        trait_code="preference.affinity",
        slot_key="slt_passive",
        value_fingerprint="val_passive",
        created_at=500.0,
        author_type="external",
        evidence_class="external_observation",
    )
    store = _store(
        db_path,
        visible_event_ids={
            "event-like",
            "event-style",
            "event-third",
            "event-passive",
        },
    )

    class _LLM:
        async def generate_portrait(self, *, material: dict[str, Any]) -> dict[str, Any]:
            assert all(
                ref.startswith("event:")
                for item in material["tentative_claims"]
                for ref in item["basis_refs"]
            )
            return {"prompt_summary": ["模型覆盖了确定性自述行"]}

    projection = await UserPortraitProjectionBuilder(store, llm_client=_LLM()).build(
        "local_user"
    )

    assert projection.prompt_summary == [
        "用户曾自述：喜欢「没有人声的音乐」（尚未形成长期结论）",
        "用户曾自述：偏好的沟通方式是「先讲结论」（尚未形成长期结论）",
    ]
    assert projection.generated_by == "rule"
    assert projection.evidence_refs == ["event:event-like", "event:event-style"]
    assert "用户讨厌所有音乐" not in "\n".join(projection.prompt_summary)
    assert "不可见内容" not in "\n".join(projection.prompt_summary)
    assert "被动观察内容" not in "\n".join(projection.prompt_summary)
    assert "明日香" not in "\n".join(projection.prompt_summary)


@pytest.mark.asyncio
async def test_query_uses_latest_route_and_dedupes_current_portrait_assertions(tmp_path) -> None:
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    for claim_id, event_id, created_at in (
        ("claim-world", "event-world", 100.0),
        ("claim-duplicate", "event-duplicate", 110.0),
        ("claim-current-review", "event-review", 120.0),
    ):
        _seed_claim(
            db_path,
            claim_id=claim_id,
            event_id=event_id,
            predicate="LIKES",
            object_value="纯音乐",
            family="preference_profile",
            trait_code="preference.affinity",
            slot_key="slt_music",
            value_fingerprint="val_music",
            created_at=created_at,
        )
    _seed_assertion_outcome(
        db_path,
        claim_id="claim-world",
        assertion_id="assert-world",
        created_at=130.0,
    )
    _seed_assertion_outcome(
        db_path,
        claim_id="claim-current-review",
        assertion_id="assert-review",
        created_at=131.0,
    )
    _seed_claim(
        db_path,
        claim_id="claim-stale-route",
        event_id="event-stale-route",
        predicate="LIKES",
        object_value="旧路线内容",
        family="preference_profile",
        trait_code="preference.affinity",
        slot_key="slt_old",
        value_fingerprint="val_old",
        created_at=90.0,
    )
    with sqlite3.connect(db_path) as db:
        _seed_route_outcome(
            db,
            claim_id="claim-stale-route",
            outcome_id="route:claim-stale-route:2",
            outcome="unrouted",
            family="preference_profile",
            trait_code="preference.affinity",
            slot_key="slt_old",
            value_fingerprint="val_old",
            created_at=200.0,
        )
        db.commit()
    store = _store(
        db_path,
        visible_event_ids={
            "event-world",
            "event-duplicate",
            "event-review",
            "event-stale-route",
        },
    )

    candidates = await list_tentative_portrait_claims(
        store,
        user_id="local_user",
        current_assertion_ids={"assert-world", "assert-review"},
        visible_assertion_ids={"assert-world"},
    )

    assert candidates == []


@pytest.mark.asyncio
async def test_tombstone_and_expiry_remove_cached_tentative_lines_immediately(
    tmp_path,
    monkeypatch,
) -> None:
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    clock = [150.0]
    monkeypatch.setattr(
        "magi.user_profile.portrait_claim_query.time.time",
        lambda: clock[0],
    )
    _seed_claim(
        db_path,
        claim_id="claim-expiring",
        event_id="event-expiring",
        predicate="LIKES",
        object_value="夜间散步",
        family="preference_profile",
        trait_code="preference.affinity",
        slot_key="slt_expiring",
        value_fingerprint="val_expiring",
        created_at=100.0,
        fact_valid_to=200.0,
    )
    store = _store(db_path, visible_event_ids={"event-expiring"})
    projection = await UserPortraitProjectionBuilder(store).build("local_user")
    assert "夜间散步" in "\n".join(projection.prompt_summary)

    clock[0] = 250.0
    assert await portrait_projection_is_stale(
        projection,
        user_id="local_user",
        l2_store=store,
    )
    expired = await UserPortraitProjectionBuilder(store).build("local_user")
    assert "夜间散步" not in "\n".join(expired.prompt_summary)

    _seed_claim(
        db_path,
        claim_id="claim-forgotten",
        event_id="event-forgotten",
        predicate="INTERESTED_IN",
        object_value="旅行摄影",
        family="interest_profile",
        trait_code="interest.attention",
        slot_key="slt_forget",
        value_fingerprint="val_forget",
        created_at=180.0,
    )

    async def resolve_visible_events(event_ids: list[str]) -> dict[str, float]:
        return {
            event_id: 1_700_000_000.0
            for event_id in event_ids
            if event_id in {"event-expiring", "event-forgotten"}
        }

    store._evidence_timestamp_resolver = resolve_visible_events
    visible = await UserPortraitProjectionBuilder(store).build("local_user")
    assert "旅行摄影" in "\n".join(visible.prompt_summary)

    assert await store.tombstone_source_events(
        ["event-forgotten"],
        reason="user_request",
    ) == 1
    assert await portrait_projection_is_stale(
        visible,
        user_id="local_user",
        l2_store=store,
    )
    forgotten = await UserPortraitProjectionBuilder(store).build("local_user")
    assert "旅行摄影" not in "\n".join(forgotten.prompt_summary)
