"""Direct preference negation closes current projections without inventing opposites."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import aiosqlite
import pytest

from magi.events.events import EventLevel, EventTypes
from magi.memory.l2.claims.preference_exclusions import (
    reconcile_preference_exclusions_on_connection,
)
from magi.memory.l2.claims.reprojection_write import reproject_claim_route
from magi.memory.l2.corrections.models import CorrectionKind
from magi.memory.l2.semantic_routing import (
    ProjectionTarget,
    RouteDisposition,
    derive_semantic_route,
)
from magi.user_profile.portrait_projection_builder import UserPortraitProjectionBuilder

from .test_claim_text_pipeline import APPLE_ID, _entity, _open_store, _response
from .test_semantic_routing import _route_input


async def _read(store, query: str, args: tuple = ()) -> list[dict]:
    async with aiosqlite.connect(store.l2.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, args) as cursor:
            return [dict(row) for row in await cursor.fetchall()]


async def _open(base: Path):
    store, adapter = await _open_store(base, "{}")
    await store.l2_entity_catalog.upsert_entity(
        entity_id=APPLE_ID,
        canonical_name="苹果",
        entity_type="other",
    )
    return store, adapter


async def _say(
    store,
    adapter,
    event_id: str,
    *,
    negative: bool = False,
    predicate: str = "LIKES",
    observed_at: float | None = None,
    cue: str = "unspecified",
    raw: str = "",
    calendar_expression: dict[str, object] | None = None,
) -> float:
    phrase = "喜欢" if predicate == "LIKES" else "讨厌"
    content = f'我{raw}{"不再" if negative else "一直"}{phrase}苹果'
    adapter._responses.append(
        _response(
            event_id=event_id,
            object_ref=APPLE_ID,
            evidence=content,
            entities=[_entity("苹果", "苹果", "other", resolved_id=APPLE_ID)],
            predicate=predicate,
            polarity="negative" if negative else "positive",
            temporal_cue=cue,
            raw_time_expression=raw,
            calendar_expression=calendar_expression,
        )
    )
    # The initial fallback is consumed only if a test unexpectedly makes another model call.
    if adapter._responses[0] == "{}":
        adapter._responses.pop(0)
    before = store.get_l2_pipeline_stats()["extract_completed"]
    observed_at = time.time() if observed_at is None else observed_at
    result = await store.ingest_event(
        {
            "id": event_id,
            "type": EventTypes.USER_MESSAGE,
            "timestamp": observed_at,
            "source": "chat",
            "level": EventLevel.INFO.value,
            "data": {
                "user_id": "u1",
                "session_id": f"session-{event_id}",
                "content": content,
                "metadata": {"_temporal": {"calendar_timezone_id": "Asia/Shanghai"}},
            },
        }
    )
    assert result["l2_job_enqueued"]
    for _ in range(800):
        stats = store.get_l2_pipeline_stats()
        if stats["extract_completed"] > before or stats["extract_failed"]:
            break
        await asyncio.sleep(0.01)
    assert stats["extract_failed"] == 0, stats
    assert stats["extract_completed"] == before + 1, stats
    return observed_at


async def _reconcile(store) -> None:
    async with aiosqlite.connect(store.l2.db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("BEGIN IMMEDIATE")
        await reconcile_preference_exclusions_on_connection(
            db, subject_ids=["user:u1"], now=time.time()
        )
        await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("predicate", ["LIKES", "DISLIKES"])
async def test_negative_closes_confirmed_current_keeps_history_and_no_opposite(tmp_path, predicate):
    store, adapter = await _open(tmp_path)
    try:
        old_at = await _say(
            store, adapter, "old", predicate=predicate, observed_at=time.time() - 100
        )
        assertion = (await store.l2.list_current_assertions(entity_id="user:u1"))[0]
        await store.l2.apply_user_feedback(
            assertion_id=assertion["assertion_id"], feedback="confirmed"
        )
        assert (await UserPortraitProjectionBuilder(store.l2).build("u1")).prompt_summary
        cutoff = await _say(store, adapter, "negative", negative=True, predicate=predicate)
        assert await store.l2.list_current_assertions(entity_id="user:u1") == []
        rows = await _read(store, "SELECT * FROM tom_trait_assertions")
        assert len(rows) == 1 and rows[0]["status"] == "superseded"
        assert rows[0]["valid_to"] == cutoff
        edges = await _read(store, "SELECT * FROM knowledge_graph")
        assert len(edges) == 1 and edges[0]["status"] == "superseded"
        assert edges[0]["predicate"] == predicate
        historical = await store.l2.list_current_assertions(
            entity_id="user:u1", effective_at=old_at + 0.01
        )
        assert len(historical) == 1
        assert not (await UserPortraitProjectionBuilder(store.l2).build("u1")).prompt_summary
        receipts = await _read(
            store, "SELECT * FROM l2_claim_projection_outcomes WHERE target_kind='exclusion'"
        )
        assert len(receipts) == 2
        negative = next(
            c for c in await store.l2.list_grounded_claims() if c["polarity"] == "negative"
        )
        for _ in range(2):
            replay = await reproject_claim_route(store.l2.db_path, claim_id=negative["claim_id"])
            assert ProjectionTarget.EXCLUSION in replay.decision.projection_targets
            assert await store.l2.list_current_assertions(entity_id="user:u1") == []
        await _reconcile(store)
        assert (
            len(
                await _read(
                    store,
                    "SELECT * FROM l2_claim_projection_outcomes WHERE target_kind='exclusion'",
                )
            )
            == 2
        )
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_negative_without_old_positive_blocks_late_history_but_allows_later_self_report(
    tmp_path,
):
    store, adapter = await _open(tmp_path)
    try:
        cutoff = await _say(store, adapter, "negative", negative=True)
        assert not await _read(store, "SELECT * FROM tom_trait_assertions")
        await _say(store, adapter, "late-old", observed_at=cutoff - 100)
        assert await store.l2.list_current_assertions(entity_id="user:u1") == []
        assert not (await UserPortraitProjectionBuilder(store.l2).build("u1")).prompt_summary
        await _say(store, adapter, "new-positive")
        current = await store.l2.list_current_assertions(entity_id="user:u1")
        assert len(current) == 1 and current[0]["trait_value"] == "like"
        effects = await _read(store, "SELECT * FROM l2_preference_exclusion_effects")
        assert all(row["target_id"] != current[0]["assertion_id"] for row in effects)
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_forgetting_negative_restores_supported_fact_and_replay_is_blocked(tmp_path):
    store, adapter = await _open(tmp_path)
    try:
        await _say(store, adapter, "positive", observed_at=time.time() - 100)
        original = (await store.l2.list_current_assertions(entity_id="user:u1"))[0]
        await _say(store, adapter, "negative", negative=True)
        negative_claim = next(
            c for c in await store.l2.list_grounded_claims() if c["polarity"] == "negative"
        )
        await store.l2.forget_source_events(["negative"], reason="user_deleted_source")
        current = await store.l2.list_current_assertions(entity_id="user:u1")
        assert len(current) == 1 and current[0]["assertion_id"] == original["assertion_id"]
        assert current[0]["status"] == original["status"] and current[0]["valid_to"] is None
        assert (await _read(store, "SELECT * FROM knowledge_graph"))[0]["status"] != "superseded"
        assert not await _read(store, "SELECT * FROM l2_preference_exclusion_effects")
        assert not (
            await reproject_claim_route(store.l2.db_path, claim_id=negative_claim["claim_id"])
        ).claim_active
        await _reconcile(store)
        assert len(await store.l2.list_current_assertions(entity_id="user:u1")) == 1
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_forgetting_all_support_never_restores_old_preference(tmp_path):
    store, adapter = await _open(tmp_path)
    try:
        await _say(store, adapter, "positive", observed_at=time.time() - 100)
        await _say(store, adapter, "negative", negative=True)
        await store.l2.forget_source_events(["positive", "negative"], reason="user_deleted_sources")
        assert await store.l2.list_current_assertions(entity_id="user:u1") == []
        assert not await _read(store, "SELECT * FROM l2_preference_exclusion_effects")
        assert not (await UserPortraitProjectionBuilder(store.l2).build("u1")).prompt_summary
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_later_user_correction_is_not_overwritten_when_negative_source_is_deleted(tmp_path):
    store, adapter = await _open(tmp_path)
    try:
        await _say(store, adapter, "positive", observed_at=time.time() - 100)
        await _say(store, adapter, "negative", negative=True)
        await _say(store, adapter, "new-positive")
        current = (await store.l2.list_current_assertions(entity_id="user:u1"))[0]
        correction = await store.l2.apply_assertion_correction(
            assertion_id=current["assertion_id"],
            request_id="correct-preference",
            actor_id="user:u1",
            correction_kind=CorrectionKind.RECORD_ERROR,
            replacement_value="dislike",
        )
        assert correction is not None
        await store.l2.forget_source_events(["negative"], reason="user_deleted_source")
        await _reconcile(store)
        after = await store.l2.list_current_assertions(entity_id="user:u1")
        assert len(after) == 1 and after[0]["trait_value"] == "dislike"
        assert after[0]["authority_ref"]
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_current_recent_expression_uses_trusted_source_boundary(tmp_path):
    store, adapter = await _open(tmp_path)
    try:
        await _say(store, adapter, "positive", observed_at=time.time() - 100)
        await _say(
            store, adapter, "negative", negative=True, cue="recent", raw="现在",
            calendar_expression={"kind": "at_observation"},
        )
        negative = next(
            c for c in await store.l2.list_grounded_claims() if c["polarity"] == "negative"
        )
        assert negative["raw_time_frame"]["resolution"] == "observation_anchor"
        assert await store.l2.list_current_assertions(entity_id="user:u1") == []
    finally:
        await store.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["现在", "之前那阵子", "某段时间"])
@pytest.mark.parametrize("meaning", [None, {"kind": "relative_period", "unit": "day", "offset": "invalid"}])
async def test_unresolved_negative_time_preserves_current_positive(tmp_path, raw, meaning):
    store, adapter = await _open(tmp_path)
    try:
        await _say(store, adapter, "positive", observed_at=time.time() - 100)
        original = (await store.l2.list_current_assertions(entity_id="user:u1"))[0]
        await _say(
            store, adapter, "negative", negative=True, cue="recent", raw=raw,
            calendar_expression=meaning,
        )
        negative = next(
            claim for claim in await store.l2.list_grounded_claims()
            if claim["polarity"] == "negative"
        )
        assert negative["raw_time_frame"]["resolution"] == "unresolved_text"
        for _ in range(2):
            route = await reproject_claim_route(store.l2.db_path, claim_id=negative["claim_id"])
            assert route.decision.disposition is RouteDisposition.DEFERRED
            assert not route.decision.projection_targets
        current = await store.l2.list_current_assertions(entity_id="user:u1")
        assert [(row["assertion_id"], row["trait_value"], row["valid_to"]) for row in current] == [
            (original["assertion_id"], "like", None)
        ]
        assert await _read(store, "SELECT * FROM l2_preference_exclusion_effects") == []
        assert (await UserPortraitProjectionBuilder(store.l2).build("u1")).prompt_summary
    finally:
        await store.shutdown()


@pytest.mark.parametrize(
    ("cue", "raw", "resolution", "expected"),
    [
        ("unspecified", "", "unscheduled", True),
        ("recent", "现在", "unresolved_text", False),
        ("recent", "currently", "unresolved_text", False),
        ("recent", "现在", "observation_anchor", True),
        ("unspecified", "此刻", "observation_anchor", True),
        ("one_off", "现在", "observation_anchor", False),
        ("recent", "今天", "calendar_anchor", False),
        ("recent", "tomorrow", "calendar_anchor", False),
        ("recent", "现在", "low", False),
        ("one_off", "", "unscheduled", False),
        ("unspecified", "过去", "unresolved_text", False),
    ],
)
def test_exclusion_time_boundary_is_typed_not_language_wordlist(cue, raw, resolution, expected):
    route = derive_semantic_route(
        _route_input(
            "LIKES",
            subject_type="user",
            subject_id="user:u1",
            polarity="negative",
            specificity="concrete",
            temporal_cue=cue,
            raw_time_expression=raw,
            time_resolution=resolution,
        )
    )
    assert (ProjectionTarget.EXCLUSION in route.projection_targets) is expected
    assert route.disposition is (RouteDisposition.ROUTED if expected else RouteDisposition.DEFERRED)


@pytest.mark.asyncio
async def test_route_reprojection_releases_exclusion_when_identity_is_retired(tmp_path):
    store, adapter = await _open(tmp_path)
    try:
        await _say(store, adapter, "positive", observed_at=time.time() - 100)
        await _say(store, adapter, "negative", negative=True)
        negative = next(
            c for c in await store.l2.list_grounded_claims() if c["polarity"] == "negative"
        )
        async with aiosqlite.connect(store.l2.db_path) as db:
            await db.execute(
                "UPDATE l2_claim_entity_refs SET invalidated_at = ?, invalidated_reason = 'entity_retired' WHERE claim_id = ? AND ref_role = 'object'",
                (time.time(), negative["claim_id"]),
            )
            await db.commit()
        result = await reproject_claim_route(store.l2.db_path, claim_id=negative["claim_id"])
        assert result.decision.disposition is RouteDisposition.ROUTED
        assert result.decision.semantic_target_key.startswith("text:")
        assert len(await store.l2.list_current_assertions(entity_id="user:u1")) == 1
        assert not await _read(store, "SELECT * FROM l2_preference_exclusion_effects")
    finally:
        await store.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["valid_to", "expires_at"])
async def test_negative_never_extends_already_ended_history(tmp_path, field):
    store, adapter = await _open(tmp_path)
    try:
        await _say(store, adapter, "positive", observed_at=time.time() - 100)
        assertion = (await store.l2.list_current_assertions(entity_id="user:u1"))[0]
        ended_at = time.time() - 50
        async with aiosqlite.connect(store.l2.db_path) as db:
            await db.execute(
                f"UPDATE tom_trait_assertions SET {field} = ? WHERE assertion_id = ?",
                (ended_at, assertion["assertion_id"]),
            )
            await db.commit()
        await _say(store, adapter, "negative", negative=True)
        row = (await _read(store, "SELECT * FROM tom_trait_assertions"))[0]
        assert row[field] == ended_at
        assert row["status"] == assertion["status"]
        assert not await _read(
            store, "SELECT * FROM l2_preference_exclusion_effects WHERE target_kind='assertion'"
        )
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_late_negative_cannot_override_newer_user_confirmation(tmp_path):
    store, adapter = await _open(tmp_path)
    try:
        old_at = await _say(store, adapter, "positive", observed_at=time.time() - 100)
        assertion = (await store.l2.list_current_assertions(entity_id="user:u1"))[0]
        await store.l2.apply_user_feedback(
            assertion_id=assertion["assertion_id"], feedback="confirmed"
        )
        await _say(store, adapter, "negative", negative=True, observed_at=old_at + 50)
        current = await store.l2.list_current_assertions(entity_id="user:u1")
        assert len(current) == 1 and current[0]["assertion_id"] == assertion["assertion_id"]
        assert current[0]["validation_state"] == "stable"
        assert (await _read(store, "SELECT * FROM knowledge_graph"))[0]["status"] != "superseded"
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_later_terminal_correction_is_not_reversed_by_deleting_negative(tmp_path):
    store, adapter = await _open(tmp_path)
    try:
        await _say(store, adapter, "positive", observed_at=time.time() - 100)
        await _say(store, adapter, "negative", negative=True)
        await _say(store, adapter, "new-positive")
        current = (await store.l2.list_current_assertions(entity_id="user:u1"))[0]
        result = await store.l2.apply_assertion_correction(
            assertion_id=current["assertion_id"],
            request_id="reject-preference",
            actor_id="user:u1",
            correction_kind=CorrectionKind.RECORD_ERROR,
        )
        assert result is not None
        await store.l2.forget_source_events(["negative"], reason="user_deleted_source")
        await _reconcile(store)
        assert await store.l2.list_current_assertions(entity_id="user:u1") == []
        assert not (await UserPortraitProjectionBuilder(store.l2).build("u1")).prompt_summary
    finally:
        await store.shutdown()
