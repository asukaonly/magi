"""Exercise accepted chat handoff and recovery against real SQLite stores."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import sys
import time
from types import SimpleNamespace

import pytest
import pytest_asyncio

from magi.agent.post_turn_understanding import PostTurnUnderstandingService
from magi.chat import ChatMessageRecord, ChatStore
from magi.memory.post_turn_contracts import PostTurnLeaseLost
from magi.core.sqlite import sqlite_connection_async
from magi.memory.l0.attention import AttentionActionType, AttentionKind, AttentionUpdateAction
from magi.memory.unified_store import MemoryStoreTuning, UnifiedMemoryStore
from magi.personality.interaction_analyzer import DEFAULT_ANALYSIS, InteractionObservation
from magi.personality.interaction_batch_analyzer import BatchInteractionAnalysis
from magi.personality.loader import PersonalityConfig
from magi.personality.self_memory import SelfMemory


async def _sql(path, statement, params=()):
    async with sqlite_connection_async(str(path)) as db:
        rows = await db.execute_fetchall(statement, params)
        await db.commit()
        return [tuple(row) for row in rows]


async def _accept(store, *, suffix="one", persona_id="original", fail=False):
    now = int(time.time() * 1000)
    turn_id = f"turn-{suffix}"
    created = await store.create_user_turn_once(
        session_id="session", user_id="user", turn_id=turn_id,
        message_text="Correction: please keep answers brief.", created_at_ms=now,
        persona_id=persona_id, runtime_envelope={"message": "synthetic"},
        request_fingerprint=suffix,
    )
    await store.mark_user_turn_delivery_queued(
        turn_id=turn_id, delivery_attempt_no=created.delivery_attempt_no, command_id=1, updated_at_ms=now,
    )
    await store.mark_user_turn_delivery_admitted(
        turn_id=turn_id, delivery_attempt_no=created.delivery_attempt_no, command_id=1, updated_at_ms=now,
    )
    message = ChatMessageRecord(
        message_id=f"assistant-{suffix}", session_id="session", turn_id=turn_id, user_id="user",
        role="assistant", message_kind="assistant_final", content_text="I will keep answers brief.",
        payload_json="{}", is_final=True, is_visible=True, created_at_ms=now, sequence_no=0,
        replaces_message_id=None, replaced_by_message_id=None, persona_id=persona_id,
    )
    if fail:
        await _sql(store.db_path, """CREATE TRIGGER fail_intent BEFORE INSERT ON chat_post_turn_outcomes
            BEGIN SELECT RAISE(ABORT, 'synthetic intent failure'); END""")
    result = await store.commit_user_turn_assistant_outcome(
        turn_id=turn_id, delivery_attempt_no=created.delivery_attempt_no, command_id=1,
        messages=[message], attachment_payloads_by_message_id={}, trace_id=None,
        execution_mode="direct_llm", ux_plan={}, response_mode="final_only", started_at_ms=now,
        completed_at_ms=now + 1, run_id=None, run_revision=0, run_disposition=None,
    )
    assert result
    return f"chat-message:assistant-{suffix}:accepted"


async def _open_memory(paths):
    memory = UnifiedMemoryStore(
        persist_dir=str(paths.memory_dir), memory_db_path=str(paths.memory_db_path),
        enable_l0=True, enable_l1=False, enable_l2=True, enable_l3=False, enable_l4=True,
        memory_config_getter=lambda: SimpleNamespace(l0=SimpleNamespace(
            attention_update_turn_threshold=1, attention_update_idle_seconds=30,
            attention_update_max_delay_seconds=90,
        )),
        tuning=MemoryStoreTuning(enable_l1_vectors=False, enable_l2_vectors=False,
                                enable_l3_vectors=False, enable_l4_vectors=False,
                                async_embeddings=False, enable_l3_llm_summary=False),
    )
    await memory.initialize()
    return memory


@pytest_asyncio.fixture
async def runtime(runtime_paths_with_schema, monkeypatch):
    paths = runtime_paths_with_schema
    monkeypatch.setattr("magi.personality.self_memory.get_runtime_paths", lambda: paths)
    persona = SelfMemory("test", persona_id="original", personality_config=PersonalityConfig(name="test"))
    await persona.init()
    memory = await _open_memory(paths)
    calls = []

    async def analyze(batch, **kwargs):
        calls.append(tuple(turn.turn_id for turn in batch))
        observations = [
            InteractionObservation("task_preference", {
                "task_category": "chat", "preference": "brief answers", "evidence_text": "keep answers brief",
                "confidence": 0.9,
            }),
            InteractionObservation("profile_signal", {
                "trait_family": "communication_profile", "trait_name": "response_style", "trait_value": "brief",
                "evidence_text": "keep answers brief", "confidence": 0.9,
            }),
        ]
        return BatchInteractionAnalysis(
            turn_analyses={turn.turn_id: replace(DEFAULT_ANALYSIS, memory_observations=observations) for turn in batch},
            attention_actions=tuple(AttentionUpdateAction(
                action=AttentionActionType.ADD, kind=AttentionKind.CONSTRAINT,
                summary="The user prefers concise responses.", source_turn_ids=(turn.turn_id,),
            ) for turn in batch),
        )

    monkeypatch.setattr("magi.agent.post_turn_understanding.analyze_interaction_batch", analyze)
    services = []

    def service(store=None, personality=None):
        result = PostTurnUnderstandingService(
            unified_memory=memory, self_memory=personality or persona,
            chat_store=store or ChatStore(db_path=str(paths.chat_db_path)),
        )
        services.append(result)
        return result

    yield SimpleNamespace(paths=paths, memory=memory, persona=persona, calls=calls, service=service)
    for item in services:
        await item.shutdown(flush=False)
    await memory.shutdown()


async def _drain(service):
    assert await service.recover_ready_once() > 0
    assert await service.scheduler.wait_idle(timeout_seconds=5)


@pytest.mark.asyncio
async def test_acceptance_transaction_rolls_back_when_handoff_cannot_persist(runtime):
    store = ChatStore(db_path=str(runtime.paths.chat_db_path))
    with pytest.raises(sqlite3.IntegrityError, match="synthetic intent failure"):
        await _accept(store, fail=True)
    assert await _sql(store.db_path, "SELECT message_id FROM chat_messages WHERE role='assistant'") == []
    assert await _sql(store.db_path, "SELECT * FROM chat_post_turn_outcomes") == []
    assert await _sql(store.db_path, "SELECT delivery_state FROM chat_user_turn_delivery") == [("admitted",)]


@pytest.mark.asyncio
async def test_restart_without_live_admission_uses_original_persona_and_checkpoints(runtime):
    store = ChatStore(db_path=str(runtime.paths.chat_db_path))
    outcome_id = await _accept(store)
    switched = SelfMemory("new", persona_id="switched", personality_config=PersonalityConfig(name="new"))
    await switched.init()
    service = runtime.service(personality=switched)
    await _drain(service)
    assert await service.get_status() == {"pending": 0, "claimed": 0, "failed": 0, "error_kinds": []}
    assert await _sql(runtime.paths.growth_db_path, "SELECT persona_id, total_interactions FROM relationships") == [("original", 1)]
    assert await _sql(runtime.paths.emotional_db_path, "SELECT persona_id, COUNT(*) FROM emotional_events GROUP BY persona_id") == [("original", 1)]
    assert await _sql(runtime.paths.memory_db_path, "SELECT outcome_id FROM l0_outcome_receipts") == [(outcome_id,)]
    assert await _sql(runtime.paths.memory_db_path, "SELECT COUNT(*) FROM l0_attention_items") == [(1,)]
    assert len(runtime.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_effect", ["l0", "personality", "observations"])
async def test_crash_after_effect_before_ack_reuses_frozen_analysis_exactly_once(runtime, monkeypatch, failed_effect):
    store = ChatStore(db_path=str(runtime.paths.chat_db_path))
    await _accept(store)
    original = store.settle_post_turn_effect

    async def crash(lease, effect):
        if effect.split(":")[0] == failed_effect:
            raise RuntimeError("synthetic sensitive detail must not reach status")
        await original(lease, effect)

    monkeypatch.setattr(store, "settle_post_turn_effect", crash)
    service = runtime.service(store)
    await _drain(service)
    assert (await service.get_status())["pending"] == 1
    assert await _sql(store.db_path, "SELECT last_error FROM chat_post_turn_batches") == [("RuntimeError",)]
    await service.shutdown(flush=False)
    await _sql(store.db_path, "UPDATE chat_post_turn_batches SET next_attempt_at_ms=0")
    await runtime.memory.shutdown()
    reopened_memory = await _open_memory(runtime.paths)
    reopened_persona = SelfMemory("test", persona_id="original", personality_config=PersonalityConfig(name="test"))
    await reopened_persona.init()
    restarted = PostTurnUnderstandingService(
        unified_memory=reopened_memory, self_memory=reopened_persona,
        chat_store=ChatStore(db_path=store.db_path),
    )
    try:
        await _drain(restarted)
    finally:
        await restarted.shutdown(flush=False)
        await reopened_memory.shutdown()
    assert (await restarted.get_status())["pending"] == 0
    assert len(runtime.calls) == 1
    assert await _sql(runtime.paths.growth_db_path, "SELECT total_interactions FROM relationships") == [(1,)]
    assert await _sql(runtime.paths.emotional_db_path, "SELECT COUNT(*) FROM emotional_events") == [(1,)]
    assert await _sql(runtime.paths.memory_db_path, "SELECT COUNT(*) FROM l0_attention_items") == [(1,)]
    assert await _sql(runtime.paths.memory_db_path, "SELECT total_attempts FROM procedural_skills WHERE skill_category='task_preference'") == [(1,)]
    assert await _sql(runtime.paths.memory_db_path, "SELECT COUNT(*) FROM post_turn_effect_receipts") == [(2,)]


@pytest.mark.asyncio
async def test_lease_exclusivity_expiry_and_retry_budget_survive_reopen(runtime):
    store = ChatStore(db_path=str(runtime.paths.chat_db_path))
    key = await _accept(store)
    second = ChatStore(db_path=store.db_path)
    leases = await asyncio.gather(store.claim_post_turn_batch((key,)), second.claim_post_turn_batch((key,)))
    assert sum(item is not None for item in leases) == 1
    first = next(item for item in leases if item)
    await _sql(store.db_path, "UPDATE chat_post_turn_batches SET lease_expires_at_ms=0")
    with pytest.raises(PostTurnLeaseLost):
        await store.ensure_post_turn_lease(first)
    assert not await store.finish_post_turn_batch(first)
    recovered = await second.claim_post_turn_batch((key,))
    assert recovered.attempt_count == 2
    assert not await store.finish_post_turn_batch(first)
    await second.finish_post_turn_batch(recovered, error="ModelUnavailable")
    assert not await store.list_ready_post_turn_outcomes()
    for expected_attempt in (3, 4, 5):
        await _sql(store.db_path, "UPDATE chat_post_turn_batches SET next_attempt_at_ms=0")
        reopened = ChatStore(db_path=store.db_path)
        lease = await reopened.claim_post_turn_batch((key,))
        assert lease.attempt_count == expected_attempt
        await reopened.finish_post_turn_batch(lease, error="ModelUnavailable")
    service = runtime.service()
    assert await service.get_status() == {"pending": 0, "claimed": 0, "failed": 1, "error_kinds": ["ModelUnavailable"]}
    assert not await store.list_ready_post_turn_outcomes()
    assert await service.retry_failed() == 1
    await _drain(service)
    assert (await service.get_status())["failed"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["hide", "delete", "clear"])
async def test_source_revocation_during_analysis_cannot_restore_effects(runtime, monkeypatch, mutation):
    store = ChatStore(db_path=str(runtime.paths.chat_db_path))
    await _accept(store)
    entered, release = asyncio.Event(), asyncio.Event()
    original = __import__("magi.agent.post_turn_understanding", fromlist=["analyze_interaction_batch"]).analyze_interaction_batch

    async def pause(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr("magi.agent.post_turn_understanding.analyze_interaction_batch", pause)
    service = runtime.service(store)
    await service.recover_ready_once()
    await asyncio.wait_for(entered.wait(), 5)
    if mutation == "hide":
        await _sql(store.db_path, "UPDATE chat_messages SET is_visible=0 WHERE role='assistant'")
    elif mutation == "delete":
        await _sql(store.db_path, "DELETE FROM chat_messages WHERE role='user'")
    else:
        await _sql(store.db_path, "DELETE FROM chat_sessions")
    release.set()
    assert await service.scheduler.wait_idle(timeout_seconds=5)
    assert await _sql(store.db_path, "SELECT * FROM chat_post_turn_outcomes") == []
    assert await _sql(store.db_path, "SELECT * FROM chat_post_turn_batches") == []
    assert await _sql(runtime.paths.growth_db_path, "SELECT * FROM relationships") == []
    assert await _sql(runtime.paths.memory_db_path, "SELECT * FROM l0_outcome_receipts") == []
    assert await runtime.service().recover_ready_once() == 0


@pytest.mark.asyncio
async def test_checkpoint_receipt_failure_rolls_back_memory_and_database(runtime):
    store = ChatStore(db_path=str(runtime.paths.chat_db_path))
    await _accept(store)
    await _sql(runtime.paths.memory_db_path, """CREATE TRIGGER reject_checkpoint_receipt
        BEFORE INSERT ON l0_outcome_receipts BEGIN SELECT RAISE(ABORT, 'synthetic checkpoint failure'); END""")
    service = runtime.service(store)
    await _drain(service)
    assert await _sql(runtime.paths.memory_db_path, "SELECT * FROM l0_attention_items") == []
    assert await _sql(runtime.paths.memory_db_path, "SELECT * FROM l0_outcome_receipts") == []
    assert (await runtime.memory.l0.get_attention_snapshot("session"))["items"] == []
    assert await _sql(runtime.paths.growth_db_path, "SELECT * FROM relationships") == []
    assert await _sql(store.db_path, "SELECT settled_json FROM chat_post_turn_batches") == [("[]",)]
    await _sql(runtime.paths.memory_db_path, "DROP TRIGGER reject_checkpoint_receipt")
    await _sql(store.db_path, "UPDATE chat_post_turn_batches SET next_attempt_at_ms=0")
    await _drain(service)
    assert len(runtime.calls) == 1
    assert await _sql(runtime.paths.memory_db_path, "SELECT COUNT(*) FROM l0_attention_items") == [(1,)]


@pytest.mark.asyncio
async def test_frozen_batch_membership_precedes_new_work_on_recovery(runtime):
    store = ChatStore(db_path=str(runtime.paths.chat_db_path))
    keys = (await _accept(store, suffix="one"), await _accept(store, suffix="two"))
    first = await store.claim_post_turn_batch(keys)
    await store.finish_post_turn_batch(first, error="ProcessingInterrupted")
    await _sql(store.db_path, "UPDATE chat_post_turn_batches SET next_attempt_at_ms=0")
    third = await _accept(store, suffix="three")
    assert await store.claim_post_turn_batch((keys[0], third)) is None
    await _drain(runtime.service())
    assert runtime.calls == [keys, (third,)]
    assert await _sql(runtime.paths.growth_db_path, "SELECT total_interactions FROM relationships") == [(3,)]


@pytest.mark.asyncio
async def test_crash_on_last_lease_becomes_visible_and_manual_retry_preserves_analysis(runtime):
    store = ChatStore(db_path=str(runtime.paths.chat_db_path))
    key = await _accept(store)
    lease = await store.claim_post_turn_batch((key,))
    frozen = {"synthetic": "analysis payload"}
    await store.save_post_turn_analysis(lease, frozen)
    await store.settle_post_turn_effect(lease, "l0")
    await _sql(store.db_path, "UPDATE chat_post_turn_batches SET attempt_count=5, lease_expires_at_ms=0")
    assert await ChatStore(db_path=store.db_path).list_ready_post_turn_outcomes() == []
    assert (await store.post_turn_status())["error_kinds"] == ["LeaseExpired"]
    assert await store.retry_failed_post_turn_batches() == 1
    restarted = await store.claim_post_turn_batch((key,))
    assert restarted.analysis == frozen
    assert restarted.settled == {"l0"}
    assert restarted.attempt_count == 1


@pytest.mark.asyncio
async def test_retry_reports_outcomes_while_preserving_whole_batches(runtime):
    store = ChatStore(db_path=str(runtime.paths.chat_db_path))
    keys = (await _accept(store, suffix="one"), await _accept(store, suffix="two"))
    lease = await store.claim_post_turn_batch(keys)
    await store.finish_post_turn_batch(lease, error="ModelUnavailable")
    await _sql(store.db_path, "UPDATE chat_post_turn_batches SET state='failed'")
    assert (await runtime.service(store).get_status())["failed"] == 2
    assert await runtime.service(store).retry_failed(limit=1) == 2
    assert (await store.post_turn_status())["pending"] == 2
    assert await store.claim_post_turn_batch((keys[0],)) is None


@pytest.mark.asyncio
async def test_renewal_failure_cancels_analysis_before_any_effect(runtime, monkeypatch):
    store = ChatStore(db_path=str(runtime.paths.chat_db_path))
    await _accept(store)
    service = runtime.service(store)
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def suspended(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async def fail_renewal(lease):
        await entered.wait()
        raise sqlite3.OperationalError("synthetic renewal failure")

    monkeypatch.setattr("magi.agent.post_turn_understanding.analyze_interaction_batch", suspended)
    monkeypatch.setattr(service, "_renew_batch_lease", fail_renewal)
    await _drain(service)
    assert cancelled.is_set()
    assert await _sql(runtime.paths.growth_db_path, "SELECT * FROM relationships") == []
    assert await _sql(runtime.paths.memory_db_path, "SELECT * FROM l0_outcome_receipts") == []
    assert await _sql(store.db_path, "SELECT last_error FROM chat_post_turn_batches") == [("OperationalError",)]


@pytest.mark.asyncio
async def test_partial_observation_receipt_failure_rolls_back_only_uncommitted_target(runtime):
    store = ChatStore(db_path=str(runtime.paths.chat_db_path))
    await _accept(store)
    await _sql(runtime.paths.memory_db_path, """CREATE TRIGGER reject_profile_receipt
        BEFORE INSERT ON post_turn_effect_receipts WHEN NEW.effect_key LIKE '%profile_signal%'
        BEGIN SELECT RAISE(ABORT, 'synthetic profile receipt failure'); END""")
    service = runtime.service(store)
    await _drain(service)
    assert await _sql(runtime.paths.memory_db_path, "SELECT total_attempts FROM procedural_skills WHERE skill_category='task_preference'") == [(1,)]
    assert await _sql(runtime.paths.memory_db_path, "SELECT COUNT(*) FROM tom_trait_assertions") == [(0,)]
    settled = json.loads((await _sql(store.db_path, "SELECT settled_json FROM chat_post_turn_batches"))[0][0])
    assert "l0" in settled and len(settled) == 2
    await _sql(runtime.paths.memory_db_path, "DROP TRIGGER reject_profile_receipt")
    await _sql(store.db_path, "UPDATE chat_post_turn_batches SET next_attempt_at_ms=0")
    await _drain(service)
    assert len(runtime.calls) == 1
    assert await _sql(runtime.paths.memory_db_path, "SELECT total_attempts FROM procedural_skills WHERE skill_category='task_preference'") == [(1,)]
    assert await _sql(runtime.paths.memory_db_path, "SELECT COUNT(*) FROM tom_trait_assertions") == [(1,)]


def test_production_service_requires_durable_handoff():
    with pytest.raises(TypeError, match="chat_store"):
        PostTurnUnderstandingService(unified_memory=None, self_memory=None)
    with pytest.raises(ValueError, match="durable chat store"):
        PostTurnUnderstandingService(unified_memory=None, self_memory=None, chat_store=None)


@pytest.mark.asyncio
async def test_process_exit_after_acceptance_is_recovered_by_background_loop(runtime):
    source = """
import asyncio, os, sys
sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
from test_post_turn_durable_recovery import _accept
from magi.chat import ChatStore
asyncio.run(_accept(ChatStore(db_path=sys.argv[3])))
os._exit(0)
"""
    backend = Path(__file__).resolve().parents[2]
    child = await asyncio.create_subprocess_exec(
        sys.executable, "-c", source, str(backend / "src"), str(Path(__file__).parent),
        str(runtime.paths.chat_db_path), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    output, errors = await asyncio.wait_for(child.communicate(), 15)
    assert child.returncode == 0, (output + errors).decode()[-3000:]
    service = runtime.service()
    assert (await service.get_status())["pending"] == 1
    await service.start()

    async def wait_recovered():
        while (await service.get_status())["pending"] + (await service.get_status())["claimed"]:
            await asyncio.sleep(0.02)

    await asyncio.wait_for(wait_recovered(), 5)
    assert await _sql(runtime.paths.growth_db_path, "SELECT total_interactions FROM relationships") == [(1,)]
    assert await _sql(runtime.paths.memory_db_path, "SELECT COUNT(*) FROM l0_attention_items") == [(1,)]


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["global", "session", "assistant_message", "user_message"])
async def test_clear_marker_fences_before_physical_source_deletion(runtime, scope):
    store = ChatStore(db_path=str(runtime.paths.chat_db_path))
    key = await _accept(store)
    lease = await store.claim_post_turn_batch((key,))
    await store.save_post_turn_analysis(lease, {"synthetic": "frozen analysis"})
    if scope == "global":
        await _sql(store.db_path, "INSERT INTO chat_global_clear_intent VALUES ('global', 1, 1)")
    elif scope == "session":
        await _sql(store.db_path, "INSERT INTO chat_cleared_session_scopes VALUES ('session', 1)")
    else:
        role = "assistant" if scope == "assistant_message" else "user"
        await _sql(store.db_path, """INSERT INTO chat_cleared_message_scopes
            SELECT session_id, message_id, 1 FROM chat_messages WHERE role=?""", (role,))
    assert await _sql(store.db_path, "SELECT COUNT(*) FROM chat_messages") == [(2,)]
    assert await store.list_ready_post_turn_outcomes() == []
    assert await store.claim_post_turn_batch((key,)) is None
    with pytest.raises(PostTurnLeaseLost):
        await store.ensure_post_turn_lease(lease)
    assert not await store.finish_post_turn_batch(lease)
    await _sql(store.db_path, "UPDATE chat_post_turn_batches SET lease_expires_at_ms=0")
    reopened = ChatStore(db_path=store.db_path)
    assert await reopened.list_ready_post_turn_outcomes() == []
    assert await reopened.claim_post_turn_batch((key,)) is None
    await _sql(store.db_path, "UPDATE chat_post_turn_batches SET state='failed'")
    assert await reopened.retry_failed_post_turn_batches() == 0
