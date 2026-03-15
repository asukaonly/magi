from __future__ import annotations

import time

import pytest


@pytest.mark.asyncio
async def test_l0_checkpoint_restores_session_goal_and_tactic(tmp_path):
    from magi.memory.l0_working_memory import L0WorkingMemoryStore

    checkpoint_path = tmp_path / "l0_checkpoint.db"

    store = L0WorkingMemoryStore(
        checkpoint_db_path=str(checkpoint_path),
        checkpoint_interval_seconds=1,
        session_timeout_seconds=3600,
        restore_on_restart=True,
    )
    await store.initialize()
    await store.start_session(session_id="session-1", user_id="user-1", runtime_agent_id="agent-1")
    await store.push_goal(
        session_id="session-1",
        goal_id="goal-1",
        goal_type="task",
        description="Answer the user question",
        status="in_progress",
        priority=5,
    )
    await store.upsert_active_entity(
        session_id="session-1",
        entity_id="entity-1",
        entity_type="person",
        snapshot={"name": "Asuka"},
        relevance_score=0.9,
    )
    await store.add_temporary_tactic(
        session_id="session-1",
        scope_type="user",
        scope_id="user-1",
        tactic_type="listen_first",
        tactic_payload={"mode": "empathetic"},
        source_event_ids=["evt-1"],
        expires_at=time.time() + 300,
    )
    await store.checkpoint_session("session-1")

    restored = L0WorkingMemoryStore(
        checkpoint_db_path=str(checkpoint_path),
        checkpoint_interval_seconds=1,
        session_timeout_seconds=3600,
        restore_on_restart=True,
    )
    await restored.initialize()
    workbench = await restored.get_workbench("session-1")

    assert workbench["session"]["user_id"] == "user-1"
    assert workbench["goal_stack"][0]["goal_id"] == "goal-1"
    assert workbench["active_entities"][0]["snapshot"]["name"] == "Asuka"
    assert workbench["temporary_tactics"][0]["tactic_type"] == "listen_first"


@pytest.mark.asyncio
async def test_l0_capture_event_renews_session_activity(tmp_path):
    from magi.events.events import Event, EventLevel, EventTypes
    from magi.memory.event_contracts import normalize_runtime_event
    from magi.memory.l0_working_memory import L0WorkingMemoryStore

    checkpoint_path = tmp_path / "l0_checkpoint.db"
    store = L0WorkingMemoryStore(checkpoint_db_path=str(checkpoint_path))
    await store.initialize()

    event = Event(
        type=EventTypes.TASK_COMPLETED,
        data={"session_id": "session-2", "user_id": "user-2", "task_id": "task-1"},
        source="runtime",
        level=EventLevel.INFO,
        correlation_id="corr-1",
    )
    memory_event = normalize_runtime_event(event)

    await store.capture_event(memory_event)
    workbench = await store.get_workbench("session-2")

    assert workbench["session"]["user_id"] == "user-2"
    assert workbench["session"]["status"] == "active"
    assert workbench["session"]["last_active_at"] >= workbench["session"]["started_at"]


@pytest.mark.asyncio
async def test_l0_evicts_lru_session_when_limit_reached(tmp_path):
    from magi.memory.l0_working_memory import L0WorkingMemoryStore

    checkpoint_path = tmp_path / "l0_evict.db"
    store = L0WorkingMemoryStore(
        checkpoint_db_path=str(checkpoint_path),
        max_concurrent_sessions=3,
    )
    await store.initialize()

    # Create 3 sessions; session-1 is the oldest (LRU)
    await store.start_session(session_id="session-1")
    await store.push_goal(
        session_id="session-1", goal_id="g1",
        goal_type="task", description="goal-1",
    )
    await store.start_session(session_id="session-2")
    await store.start_session(session_id="session-3")

    # Touch session-2 so session-1 remains LRU
    (await store.start_session(session_id="session-2"))["last_active_at"] = time.time()

    assert len(store._sessions) == 3

    # Adding a 4th session should evict session-1 (LRU)
    await store.start_session(session_id="session-4")

    assert len(store._sessions) == 3
    assert "session-1" not in store._sessions
    assert "session-4" in store._sessions

    # Evicted session should have been checkpointed
    restored = L0WorkingMemoryStore(
        checkpoint_db_path=str(checkpoint_path),
        max_concurrent_sessions=100,
    )
    await restored.initialize()
    workbench = await restored.get_workbench("session-1")
    assert workbench["session"] is not None
    assert workbench["goal_stack"][0]["goal_id"] == "g1"


@pytest.mark.asyncio
async def test_l0_refresh_existing_session_does_not_evict(tmp_path):
    from magi.memory.l0_working_memory import L0WorkingMemoryStore

    checkpoint_path = tmp_path / "l0_refresh.db"
    store = L0WorkingMemoryStore(
        checkpoint_db_path=str(checkpoint_path),
        max_concurrent_sessions=2,
    )
    await store.initialize()

    await store.start_session(session_id="session-1")
    await store.start_session(session_id="session-2")

    # Refreshing an existing session should not trigger eviction
    await store.start_session(session_id="session-1")

    assert len(store._sessions) == 2
    assert "session-1" in store._sessions
    assert "session-2" in store._sessions
