from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import aiosqlite
import pytest

from _shared.memory_schema import apply_memory_shared_schema
from magi.agent.post_turn_understanding import (
    AcceptedConversationOutcome,
    PostTurnUnderstandingService,
)
from magi.memory.event_contracts import (
    IngestTarget,
    MemoryDomain,
    MemoryEvent,
    RetentionClass,
    TomDepth,
)
from magi.memory.forgetting import (
    DurableForgetRunner,
    SourceForgetBatch,
    SourceForgetClaim,
    SourceForgetGateResult,
    SourceForgetIdentity,
    SourceForgetOwnerRegistry,
    SourceForgetOwnerUnavailableError,
)
from magi.memory.forgetting.references import ForgetReferenceBuilder
from magi.memory.l3.daily_mood.models import DailyMoodAggregate
from magi.memory.l3.daily_mood.store import DailyMoodAggregateStore
from magi.memory.operation_barrier import AsyncOperationBarrier
from magi.memory.source_event_governance import business_source_references
from magi.memory.store_source_event_forgetting import UnifiedSourceEventForgettingMixin
from magi.memory.unified_store import MemoryStoreTuning, UnifiedMemoryStore


class _FakeL1:
    def __init__(self) -> None:
        self.events = {"evt-1": {"event_id": "evt-1", "turn_id": "turn-1", "deleted_at": None}}
        self.deleted: list[str] = []
        self.get_event_calls: list[str] = []
        self.raw_identity_batches: list[tuple[str, ...]] = []

    async def get_event(self, event_id: str):
        self.get_event_calls.append(event_id)
        event = self.events.get(event_id)
        return dict(event) if event is not None else None

    async def get_raw_event_active_states(self, event_ids: list[str]):
        return {
            event_id: self.events[event_id]["deleted_at"] is None
            for event_id in event_ids
            if event_id in self.events
        }

    async def get_raw_event_source_identities(self, event_ids: list[str]):
        self.raw_identity_batches.append(tuple(event_ids))
        return {
            event_id: {
                "event_type": str(self.events[event_id].get("event_type") or "UserMessage"),
                "source": str(self.events[event_id].get("source") or "chat"),
                "source_item_id": self.events[event_id].get("source_item_id"),
                "idempotency_key": self.events[event_id].get("idempotency_key"),
                "turn_id": self.events[event_id].get("turn_id"),
            }
            for event_id in event_ids
            if event_id in self.events
        }

    async def mark_deleted_many(self, event_ids: list[str]) -> int:
        await asyncio.sleep(0)
        changed = 0
        for event_id in event_ids:
            event = self.events.get(event_id)
            if event is None or event["deleted_at"] is not None:
                continue
            event["deleted_at"] = 1.0
            self.deleted.append(event_id)
            changed += 1
        return changed


class _FakeL0:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.references: list[tuple[str, ...]] = []

    async def forget_attention_items(self, source_references) -> int:
        self.calls.append("l0")
        self.references.append(tuple(source_references))
        return 1


class _FakeLayer:
    def __init__(self, name: str, calls: list[str], *, fail_once: bool = False) -> None:
        self.name = name
        self.calls = calls
        self.fail_once = fail_once
        self.event_batches: list[tuple[str, ...]] = []

    async def forget_source_events(self, event_ids, **kwargs):
        _ = kwargs
        self.event_batches.append(tuple(event_ids))
        self.calls.append(self.name)
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError(f"{self.name} cleanup failed")
        return 1


class _UnifiedHarness(UnifiedSourceEventForgettingMixin):
    def __init__(self, db_path: Path, *, fail_l3_once: bool = False) -> None:
        self.memory_db_path = str(db_path)
        self.calls: list[str] = []
        self.l0 = _FakeL0(self.calls)
        self.l1 = _FakeL1()
        self.l2 = _FakeLayer("l2", self.calls)
        self.l2_entity_catalog = None
        self.l3 = _FakeLayer("l3", self.calls, fail_once=fail_l3_once)
        self.l4 = _FakeLayer("l4", self.calls)
        self._write_lock = asyncio.Lock()
        self._clear_barrier = AsyncOperationBarrier()
        self._durable_forget_runner = DurableForgetRunner(self)


class _FailingEntityCatalog:
    async def prepare_source_event_forgetting(self, _event_ids):
        raise RuntimeError("entity vector delete failed")

    async def finish_source_event_forgetting(self, _entity_ids, *, updated_after: float):
        _ = updated_after
        return 0


async def _create_memory_schema(db_path: Path) -> None:
    await apply_memory_shared_schema(str(db_path))


class _ClaimingSourceOwner:
    def __init__(self, result: SourceForgetGateResult) -> None:
        self.result = result

    async def gate(
        self,
        _batch: SourceForgetBatch,
    ) -> SourceForgetGateResult:
        return self.result

    async def finalize(
        self,
        _claims: tuple[SourceForgetClaim, ...],
    ) -> None:
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("claim_source", "claim_item_id"),
    (
        ("other-source", "item-1"),
        ("owned-source", "other-item"),
    ),
)
async def test_source_owner_cannot_claim_an_unrouted_source_identity(
    claim_source: str,
    claim_item_id: str,
) -> None:
    registry = SourceForgetOwnerRegistry()
    registry.register(
        "owned-source",
        _ClaimingSourceOwner(
            SourceForgetGateResult(
                claims=(
                    SourceForgetClaim(
                        source=claim_source,
                        source_item_id=claim_item_id,
                        event_ids=("current-event",),
                    ),
                ),
            )
        ),
    )

    with pytest.raises(RuntimeError, match="claim outside its source batch"):
        await registry.gate(
            SourceForgetBatch(
                operation_id="forget:claim-boundary",
                selector_kind="known_events",
                identities=(
                    SourceForgetIdentity(
                        event_id="selected-event",
                        source="owned-source",
                        source_item_id="item-1",
                    ),
                ),
                reason="user_forget",
                block_source_item=True,
            )
        )


@pytest.mark.asyncio
async def test_persisted_claim_requires_owner_even_for_optional_source() -> None:
    registry = SourceForgetOwnerRegistry()

    with pytest.raises(
        SourceForgetOwnerUnavailableError,
        match="Claimed source-forget owner is unavailable",
    ):
        await registry.finalize(
            (
                SourceForgetClaim(
                    source="future-source",
                    source_item_id="item-1",
                    event_ids=("event-1",),
                ),
            )
        )


@pytest.mark.asyncio
async def test_unified_forgetting_hides_l1_before_retrying_failed_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "memory.db"
    await _create_memory_schema(db_path)
    memory = _UnifiedHarness(db_path, fail_l3_once=True)

    async def forget_mood(_store, _event_ids):
        memory.calls.append("mood")
        return 0

    monkeypatch.setattr(DailyMoodAggregateStore, "forget_source_events", forget_mood)

    with pytest.raises(RuntimeError, match="l3 cleanup failed"):
        await memory.forget_source_event("evt-1")

    assert memory.l1.events["evt-1"]["deleted_at"] is not None
    assert memory.calls == ["l2", "mood", "l3"]

    assert await memory.forget_source_event("evt-1") is True
    assert memory.calls[-5:] == ["l2", "mood", "l3", "l0", "l4"]
    assert memory.l0.references[-1] == ("evt-1", "turn-1")
    assert memory.l2.event_batches[-1] == ("evt-1", "turn-1")
    assert memory.l3.event_batches[-1] == ("evt-1", "turn-1")
    assert memory.l4.event_batches[-1] == ("evt-1", "turn-1")
    assert memory.l1.deleted == ["evt-1"]

    calls_after_completion = list(memory.calls)
    assert await memory.forget_source_event("evt-1") is True
    assert memory.calls == calls_after_completion
    assert memory.l1.deleted == ["evt-1"]


@pytest.mark.asyncio
async def test_barrier_and_cleanup_references_are_loaded_in_one_raw_batch(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    await _create_memory_schema(db_path)
    memory = _UnifiedHarness(db_path)
    memory.l1.events["evt-2"] = {
        "event_id": "evt-2",
        "turn_id": "turn-2",
        "deleted_at": 1.0,
    }

    references = await ForgetReferenceBuilder(
        memory_db_path=memory.memory_db_path,
        l1=memory.l1,
    ).event_references(
        ("evt-1", "evt-2", "evt-missing"),
        include_turn_references=True,
        block_source_item=True,
    )

    assert tuple(reference.value for reference in references if reference.role == "barrier") == (
        "evt-1",
        "turn-1",
        "evt-2",
        "turn-2",
        "evt-missing",
    )
    assert tuple(reference.value for reference in references if reference.role == "cleanup") == (
        "evt-1",
        "turn-1",
        "evt-2",
        "turn-2",
        "evt-missing",
    )
    assert memory.l1.raw_identity_batches == [("evt-1", "evt-2", "evt-missing")]
    assert memory.l1.get_event_calls == []


@pytest.mark.asyncio
async def test_explicit_reimport_cleanup_omits_replay_barriers(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    await _create_memory_schema(db_path)
    memory = _UnifiedHarness(db_path)

    references = await ForgetReferenceBuilder(
        memory_db_path=memory.memory_db_path,
        l1=memory.l1,
    ).event_references(
        ("evt-1",),
        include_turn_references=False,
        block_source_item=False,
        persist_replay_barriers=False,
    )

    assert [reference for reference in references if reference.role == "barrier"] == []
    assert [
        (reference.ref_type, reference.value)
        for reference in references
        if reference.role == "cleanup"
    ] == [("exact_event", "evt-1")]


@pytest.mark.asyncio
async def test_known_event_forgetting_uses_stable_sorted_batches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "memory.db"
    await _create_memory_schema(db_path)
    memory = _UnifiedHarness(db_path)

    async def forget_mood(_store, _event_ids):
        return 0

    monkeypatch.setattr(DailyMoodAggregateStore, "forget_source_events", forget_mood)
    import magi.memory.forgetting.runner as forgetting_runner

    monkeypatch.setattr(forgetting_runner, "_SELECTION_BATCH_SIZE", 1)
    memory.l1.events["evt-0"] = {
        "event_id": "evt-0",
        "turn_id": "turn-0",
        "deleted_at": None,
    }
    deleted = await memory.forget_known_source_events(
        ["evt-1", "evt-0"],
        reason="user_forget_time_range",
    )

    assert deleted == 2
    assert memory.l1.events["evt-0"]["deleted_at"] is not None
    assert memory.l1.events["evt-1"]["deleted_at"] is not None


@pytest.mark.asyncio
async def test_unowned_source_keeps_source_item_and_idempotency_barriers(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    await _create_memory_schema(db_path)
    memory = _UnifiedHarness(db_path)
    memory.l1.events["evt-1"].update(
        {
            "event_type": "plugin.activity",
            "source": "plugin-source",
            "source_item_id": "item-1",
            "idempotency_key": "idem-1",
        }
    )

    await memory.forget_known_source_events(
        ["evt-1"],
        reason="user_forget_plugin_event",
        block_source_item=True,
    )

    expected = {
        "evt-1",
        *business_source_references(
            source="plugin-source",
            event_type="plugin.activity",
            source_item_id="item-1",
            idempotency_key="idem-1",
        ),
    }
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """
            SELECT event_id
            FROM memory_source_event_tombstones
            WHERE event_id IN (?, ?, ?)
            """,
            tuple(sorted(expected)),
        ) as cursor:
            persisted = {str(row[0]) for row in await cursor.fetchall()}
    assert persisted == expected


@pytest.mark.asyncio
async def test_unified_forgetting_is_idempotent_under_concurrent_delete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "memory.db"
    await _create_memory_schema(db_path)
    memory = _UnifiedHarness(db_path)

    async def forget_mood(_store, _event_ids):
        memory.calls.append("mood")
        return 0

    monkeypatch.setattr(DailyMoodAggregateStore, "forget_source_events", forget_mood)

    results = await asyncio.gather(
        memory.forget_source_event("evt-1"),
        memory.forget_source_event("evt-1"),
    )

    assert results == [True, True]
    assert memory.l1.deleted == ["evt-1"]
    assert memory.calls == ["l2", "mood", "l3", "l0", "l4"]
    assert await memory.forget_source_event("evt-never-existed") is False


@pytest.mark.asyncio
async def test_entity_vector_failure_keeps_l1_hidden_for_recovery(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    await _create_memory_schema(db_path)
    memory = _UnifiedHarness(db_path)
    memory.l2_entity_catalog = _FailingEntityCatalog()

    with pytest.raises(RuntimeError, match="entity vector delete failed"):
        await memory.forget_source_event("evt-1")

    assert memory.calls == []
    assert memory.l1.events["evt-1"]["deleted_at"] is not None


@pytest.mark.asyncio
async def test_l1_forgetting_clears_daily_mood_without_l2(tmp_path: Path) -> None:
    memory_db = tmp_path / "memory.db"
    memory = UnifiedMemoryStore(
        persist_dir=str(tmp_path / "memory"),
        l1_db_path=str(tmp_path / "l1.db"),
        memory_db_path=str(memory_db),
        enable_l0=False,
        enable_l1=True,
        enable_l2=False,
        enable_l3=True,
        enable_l4=False,
        tuning=MemoryStoreTuning(
            enable_l1_vectors=False,
            enable_l2_vectors=False,
            enable_l3_vectors=False,
            enable_l4_vectors=False,
            enable_l3_llm_summary=False,
            async_embeddings=False,
        ),
    )
    await memory.initialize()
    try:
        assert memory.l1 is not None
        now = 1_720_000_000.0
        await memory.l1.store(
            MemoryEvent(
                event_id="evt-mood-only",
                correlation_id="corr-mood-only",
                timestamp=now,
                created_at=now,
                event_type="UserMessage",
                source="chat",
                source_item_id=None,
                memory_domain=MemoryDomain.INTERACTION,
                ingest_target=IngestTarget.L1_ONLY,
                cognition_eligible=True,
                tom_depth=TomDepth.NONE,
                retention_class=RetentionClass.COMPRESSIBLE,
                session_id="session-mood",
                turn_id="turn-mood",
                user_id="user:u1",
                task_id=None,
                content="mood source",
                author_type="user",
                content_type="text",
                importance_score=0.8,
                level=20,
            )
        )
        mood_store = DailyMoodAggregateStore(db_path=str(memory_db))
        await mood_store.initialize()
        await mood_store.upsert_aggregate(
            DailyMoodAggregate(
                day_local_date="2026-05-17",
                dominant_valence="warm",
                volatility_score=0.2,
                state_curve_compact=[0.5],
                event_count=1,
                source_event_ids=["evt-mood-only"],
            )
        )

        assert await memory.forget_source_event("evt-mood-only") is True
        assert await mood_store.get_aggregate(day_local_date="2026-05-17") is None
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_real_unified_forgetting_governs_distinct_chat_turn_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import magi.agent.post_turn_understanding as post_turn_module
    from magi.personality.interaction_analyzer import DEFAULT_ANALYSIS
    from magi.personality.interaction_batch_analyzer import (
        BatchInteractionAnalysis,
    )

    memory_db = tmp_path / "memory.db"
    await apply_memory_shared_schema(str(memory_db))
    memory = UnifiedMemoryStore(
        persist_dir=str(tmp_path / "memory"),
        l1_db_path=str(tmp_path / "l1.db"),
        memory_db_path=str(memory_db),
        enable_l0=False,
        enable_l1=True,
        enable_l2=True,
        enable_l3=False,
        enable_l4=True,
        tuning=MemoryStoreTuning(
            enable_l1_vectors=False,
            enable_l2_vectors=False,
            enable_l3_vectors=False,
            enable_l4_vectors=False,
            enable_l3_llm_summary=False,
            async_embeddings=False,
        ),
    )
    await memory.initialize()
    try:
        assert memory.l1 is not None and memory.l2 is not None and memory.l4 is not None
        now = 1_720_000_000.0
        await memory.l1.store(
            MemoryEvent(
                event_id="evt-chat-public",
                correlation_id="corr-chat",
                timestamp=now,
                created_at=now,
                event_type="UserMessage",
                source="chat",
                source_item_id=None,
                memory_domain=MemoryDomain.INTERACTION,
                ingest_target=IngestTarget.L1_ONLY,
                cognition_eligible=True,
                tom_depth=TomDepth.NONE,
                retention_class=RetentionClass.COMPRESSIBLE,
                session_id="session-1",
                turn_id="turn-private-source",
                user_id="user:u1",
                task_id=None,
                content="private source",
                author_type="user",
                content_type="text",
                importance_score=0.8,
                level=20,
            )
        )
        assertion_id = await memory.l2.upsert_assertion_candidate(
            {
                "entity_id": "user:u1",
                "entity_type": "user",
                "trait_family": "preference_profile",
                "trait_name": "private_preference",
                "trait_value": "private value",
                "confidence_score": 0.9,
                "evidence_events": ["turn-private-source"],
                "volatility_index": 0.1,
                "source_domain": "conversation",
                "inference_depth": "explicit",
                "validation_state": "stable",
                "first_inferred_at": now,
                "last_validated_at": now,
                "temporal_scope": "persistent",
            }
        )
        preference_id = await memory.l4.record_task_preference(
            user_id="user:u1",
            persona_id="seven",
            task_category="coding",
            preference="private handling preference",
            evidence_text="private source",
            confidence=0.9,
            turn_id="turn-private-source",
        )
        assert preference_id is not None

        assert await memory.forget_source_event("evt-chat-public") is True

        assertion = await memory.l2.get_tom_assertion(assertion_id=assertion_id)
        assert assertion is not None and assertion["status"] == "archived"
        assert await memory.l2.list_current_assertions(entity_id="user:u1") == []
        assert (
            await memory.l4.get_task_preferences(
                user_id="user:u1",
                task_category="coding",
            )
            == []
        )
        event = await memory.l1.get_event("evt-chat-public")
        assert event is not None and event["deleted_at"] is not None
        async with aiosqlite.connect(memory_db) as db:
            async with db.execute("""
                SELECT event_id FROM memory_source_event_tombstones
                WHERE event_id IN ('evt-chat-public', 'turn-private-source')
                ORDER BY event_id
                """) as cursor:
                assert await cursor.fetchall() == [
                    ("evt-chat-public",),
                ]
            async with db.execute(
                """
                SELECT cutoff_at
                FROM memory_source_turn_cutoffs
                WHERE turn_id = 'turn-private-source'
                """
            ) as cursor:
                cutoff_row = await cursor.fetchone()
            async with db.execute(
                """
                SELECT created_at
                FROM memory_forget_operations
                ORDER BY created_at DESC
                LIMIT 1
                """
            ) as cursor:
                operation_row = await cursor.fetchone()
        assert cutoff_row is not None and operation_row is not None
        assert float(cutoff_row[0]) == float(operation_row[0])

        async def analyze(batch, **_kwargs):  # type: ignore[no-untyped-def]
            return BatchInteractionAnalysis(
                turn_analyses={turn.turn_id: DEFAULT_ANALYSIS for turn in batch},
                attention_actions=(),
            )

        monkeypatch.setattr(
            post_turn_module,
            "analyze_interaction_batch",
            analyze,
        )
        monkeypatch.setattr(
            post_turn_module,
            "get_personality_feature_flags",
            lambda: SimpleNamespace(
                state_memory_enabled=True,
                state_transition_enabled=False,
                deep_persona_enabled=False,
            ),
        )

        class _Personality:
            def __init__(self) -> None:
                self.messages: list[str] = []

            async def process_turn_outcome(self, **kwargs):  # type: ignore[no-untyped-def]
                self.messages.append(str(kwargs["user_message"]))
                return True

        personality = _Personality()
        post_turn = PostTurnUnderstandingService(
            unified_memory=memory,
            self_memory=personality,
        )
        try:
            cutoff_at = float(cutoff_row[0])
            for outcome_id, accepted_at, message in (
                ("outcome-before-forget", cutoff_at - 1, "old"),
                ("outcome-after-forget", cutoff_at + 1, "new"),
            ):
                assert await post_turn.admit(
                    AcceptedConversationOutcome(
                        outcome_id=outcome_id,
                        source_turn_id="turn-private-source",
                        user_id="user:u1",
                        session_id="session-1",
                        user_message=message,
                        assistant_response="response",
                        epoch=memory.memory_operation_epoch(),
                        accepted_at=accepted_at,
                        immediate=True,
                    )
                )
            assert post_turn.scheduler is not None
            assert await post_turn.scheduler.wait_idle(timeout_seconds=2)
            assert personality.messages == ["new"]
        finally:
            await post_turn.shutdown(flush=False)
    finally:
        await memory.shutdown()
