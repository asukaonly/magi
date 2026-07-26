from __future__ import annotations

import time

import pytest


@pytest.mark.asyncio
async def test_l0_checkpoint_restores_session_goal_and_tactic(tmp_path):
    from magi.memory.l0.working_memory import L0WorkingMemoryStore

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
async def test_l0_workbench_excludes_execution_lane_state(tmp_path):
    from magi.memory.l0.working_memory import L0WorkingMemoryStore

    checkpoint_path = tmp_path / "l0_workbench_boundary.db"

    store = L0WorkingMemoryStore(
        checkpoint_db_path=str(checkpoint_path),
        checkpoint_interval_seconds=1,
        session_timeout_seconds=3600,
        restore_on_restart=True,
    )
    await store.initialize()
    await store.start_session(
        session_id="session-1", user_id="user-1", runtime_agent_id="chat:session-1"
    )
    await store.push_goal(
        session_id="session-1",
        goal_id="goal-1",
        goal_type="task",
        description="Investigate the login issue",
        status="in_progress",
    )

    workbench = await store.get_workbench("session-1")

    assert set(workbench) == {"session", "goal_stack", "active_entities", "temporary_tactics"}
    assert "execution" not in workbench


@pytest.mark.asyncio
async def test_l0_prompt_projection_contains_only_workbench_state(tmp_path):
    from magi.memory.l0.contracts import L0PromptWorkbenchProjection
    from magi.memory.l0.working_memory import L0WorkingMemoryStore

    checkpoint_path = tmp_path / "l0_prompt_projection.db"

    store = L0WorkingMemoryStore(
        checkpoint_db_path=str(checkpoint_path),
        checkpoint_interval_seconds=1,
        session_timeout_seconds=3600,
        restore_on_restart=True,
    )
    await store.initialize()
    await store.start_session(
        session_id="session-1", user_id="user-1", runtime_agent_id="chat:session-1"
    )
    await store.push_goal(
        session_id="session-1",
        goal_id="goal-1",
        goal_type="task",
        description="Investigate the login issue",
        status="in_progress",
    )

    projection = await store.get_prompt_workbench_projection("session-1")

    assert isinstance(projection, L0PromptWorkbenchProjection)
    payload = projection.to_payload()
    assert payload["goal_stack"][0]["description"] == (
        "Investigate the login issue"
    )
    assert "execution_summary" not in payload


@pytest.mark.asyncio
async def test_l0_capture_event_renews_session_activity(tmp_path):
    from magi.events.events import Event, EventLevel, EventTypes
    from magi.memory.event_contracts import normalize_runtime_event
    from magi.memory.l0.working_memory import L0WorkingMemoryStore

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
    from magi.memory.l0.working_memory import L0WorkingMemoryStore

    checkpoint_path = tmp_path / "l0_evict.db"
    store = L0WorkingMemoryStore(
        checkpoint_db_path=str(checkpoint_path),
        max_concurrent_sessions=3,
    )
    await store.initialize()

    # Create 3 sessions; session-1 is the oldest (LRU)
    await store.start_session(session_id="session-1")
    await store.push_goal(
        session_id="session-1",
        goal_id="g1",
        goal_type="task",
        description="goal-1",
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

    # Capacity eviction removes disposable work instead of reviving it later.
    restored = L0WorkingMemoryStore(
        checkpoint_db_path=str(checkpoint_path),
        max_concurrent_sessions=100,
    )
    await restored.initialize()
    workbench = await restored.get_workbench("session-1")
    assert workbench["session"] is None
    assert workbench["goal_stack"] == []
    await store.shutdown()
    await restored.shutdown()


@pytest.mark.asyncio
async def test_l0_refresh_existing_session_does_not_evict(tmp_path):
    from magi.memory.l0.working_memory import L0WorkingMemoryStore

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


@pytest.mark.asyncio
async def test_l0_forget_temporary_tactics_removes_live_and_checkpoint_state(tmp_path):
    from magi.memory.l0.working_memory import L0WorkingMemoryStore

    checkpoint_path = tmp_path / "l0_forget_tactics.db"
    store = L0WorkingMemoryStore(checkpoint_db_path=str(checkpoint_path))
    await store.initialize()

    await store.add_temporary_tactic(
        session_id="session-1",
        scope_type="session",
        scope_id="session-1",
        tactic_type="event-backed",
        tactic_payload={"turn_id": "turn-other"},
        source_event_ids=["event-forgotten"],
        tactic_id="tactic-event",
    )
    await store.add_temporary_tactic(
        session_id="session-1",
        scope_type="session",
        scope_id="session-1",
        tactic_type="turn-backed",
        tactic_payload={"turn_id": "turn-forgotten"},
        source_event_ids=["tool-call-other"],
        tactic_id="tactic-turn",
    )
    await store.add_temporary_tactic(
        session_id="session-1",
        scope_type="session",
        scope_id="session-1",
        tactic_type="unrelated",
        tactic_payload={"turn_id": "turn-kept"},
        source_event_ids=["event-kept"],
        tactic_id="tactic-kept",
    )
    await store.checkpoint_session("session-1")

    removed = await store.forget_temporary_tactics(
        ["event-forgotten", "turn-forgotten", "", "event-forgotten"]
    )

    assert removed == 2
    assert await store.forget_temporary_tactics(["event-forgotten", "turn-forgotten"]) == 0
    workbench = await store.get_workbench("session-1")
    assert [item["tactic_id"] for item in workbench["temporary_tactics"]] == ["tactic-kept"]

    restored = L0WorkingMemoryStore(checkpoint_db_path=str(checkpoint_path))
    await restored.initialize()
    restored_workbench = await restored.get_workbench("session-1")
    assert [item["tactic_id"] for item in restored_workbench["temporary_tactics"]] == [
        "tactic-kept"
    ]


@pytest.mark.asyncio
async def test_l0_forget_and_checkpoint_cannot_restore_deleted_tactic(tmp_path):
    from magi.memory.l0.working_memory import L0WorkingMemoryStore

    checkpoint_path = tmp_path / "l0_forget_checkpoint_race.db"
    store = L0WorkingMemoryStore(checkpoint_db_path=str(checkpoint_path))
    await store.initialize()
    await store.add_temporary_tactic(
        session_id="session-1",
        scope_type="session",
        scope_id="session-1",
        tactic_type="event-backed",
        tactic_payload={"turn_id": "turn-forgotten"},
        source_event_ids=["event-forgotten"],
        tactic_id="tactic-forgotten",
    )
    await store.checkpoint_session("session-1")

    import asyncio

    await asyncio.gather(
        store.checkpoint_session("session-1"),
        store.forget_temporary_tactics(["event-forgotten"]),
    )

    restored = L0WorkingMemoryStore(checkpoint_db_path=str(checkpoint_path))
    await restored.initialize()
    assert (await restored.get_workbench("session-1"))["temporary_tactics"] == []


@pytest.mark.asyncio
async def test_l0_forget_failure_keeps_live_tactic_for_retry(tmp_path, monkeypatch):
    from magi.memory.l0.working_memory import L0WorkingMemoryStore

    checkpoint_path = tmp_path / "l0_forget_failure.db"
    store = L0WorkingMemoryStore(checkpoint_db_path=str(checkpoint_path))
    await store.initialize()
    await store.add_temporary_tactic(
        session_id="session-1",
        scope_type="session",
        scope_id="session-1",
        tactic_type="event-backed",
        tactic_payload={"turn_id": "turn-forgotten"},
        source_event_ids=["event-forgotten"],
        tactic_id="tactic-forgotten",
    )
    await store.checkpoint_session("session-1")

    async def fail_checkpoint_read(_db, _references):
        raise RuntimeError("checkpoint unavailable")

    monkeypatch.setattr(store, "_checkpoint_tactic_ids_for_references", fail_checkpoint_read)
    with pytest.raises(RuntimeError, match="checkpoint unavailable"):
        await store.forget_temporary_tactics(["event-forgotten"])

    assert [
        item["tactic_id"] for item in (await store.get_workbench("session-1"))["temporary_tactics"]
    ] == ["tactic-forgotten"]


@pytest.mark.asyncio
async def test_l0_forget_barrier_rejects_late_tactic_and_survives_restart(tmp_path):
    from magi.memory.l0.working_memory import L0WorkingMemoryStore

    checkpoint_path = tmp_path / "l0_forget_late_write.db"
    store = L0WorkingMemoryStore(checkpoint_db_path=str(checkpoint_path))
    await store.initialize()
    assert await store.forget_temporary_tactics(["event-forgotten", "turn-forgotten"]) == 0

    rejected_by_event = await store.add_temporary_tactic(
        session_id="session-1",
        scope_type="session",
        scope_id="session-1",
        tactic_type="late-event",
        tactic_payload={"turn_id": "turn-other"},
        source_event_ids=["event-forgotten"],
        tactic_id="tactic-late-event",
    )
    rejected_by_turn = await store.add_temporary_tactic(
        session_id="session-1",
        scope_type="session",
        scope_id="session-1",
        tactic_type="late-turn",
        tactic_payload={"turn_id": "turn-forgotten"},
        source_event_ids=["event-other"],
        tactic_id="tactic-late-turn",
    )

    assert rejected_by_event is None
    assert rejected_by_turn is None
    await store.checkpoint_session("session-1")
    restored = L0WorkingMemoryStore(checkpoint_db_path=str(checkpoint_path))
    await restored.initialize()
    assert (await restored.get_workbench("session-1"))["temporary_tactics"] == []
    assert (
        await restored.add_temporary_tactic(
            session_id="session-1",
            scope_type="session",
            scope_id="session-1",
            tactic_type="late-after-restart",
            tactic_payload={"turn_id": "turn-forgotten"},
            source_event_ids=[],
        )
        is None
    )


@pytest.mark.asyncio
async def test_l0_restore_and_late_write_respect_global_source_tombstone(tmp_path):
    import json

    import aiosqlite

    from magi.memory.l0.working_memory import L0WorkingMemoryStore

    checkpoint_path = tmp_path / "l0_global_tombstone.db"
    store = L0WorkingMemoryStore(checkpoint_db_path=str(checkpoint_path))
    await store.initialize()
    await store.start_session(session_id="session-1")
    await store.checkpoint_session("session-1")

    async with aiosqlite.connect(checkpoint_path) as db:
        await db.execute("""
            CREATE TABLE memory_source_event_tombstones (
                event_id TEXT PRIMARY KEY,
                reason TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """)
        await db.execute("""
            INSERT INTO memory_source_event_tombstones(event_id, reason, created_at)
            VALUES ('event-globally-forgotten', 'user_delete_event', 1)
            """)
        await db.execute(
            """
            INSERT INTO l0_temporary_tactics(
                tactic_id, session_id, scope_type, scope_id, tactic_type,
                tactic_payload, source_event_ids, expires_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                "tactic-stale-checkpoint",
                "session-1",
                "session",
                "session-1",
                "event-backed",
                json.dumps({}),
                json.dumps(["event-globally-forgotten"]),
                1.0,
            ),
        )
        await db.commit()

    restored = L0WorkingMemoryStore(checkpoint_db_path=str(checkpoint_path))
    await restored.initialize()
    assert (await restored.get_workbench("session-1"))["temporary_tactics"] == []
    assert (
        await restored.add_temporary_tactic(
            session_id="session-1",
            scope_type="session",
            scope_id="session-1",
            tactic_type="late-event",
            tactic_payload={},
            source_event_ids=["event-globally-forgotten"],
        )
        is None
    )


@pytest.mark.asyncio
async def test_l0_concurrent_forget_and_add_never_leaves_stale_tactic(tmp_path):
    import asyncio

    from magi.memory.l0.working_memory import L0WorkingMemoryStore

    checkpoint_path = tmp_path / "l0_forget_add_race.db"
    store = L0WorkingMemoryStore(checkpoint_db_path=str(checkpoint_path))
    await store.initialize()

    await asyncio.gather(
        store.forget_temporary_tactics(["turn-forgotten"]),
        store.add_temporary_tactic(
            session_id="session-1",
            scope_type="session",
            scope_id="session-1",
            tactic_type="racing",
            tactic_payload={"turn_id": "turn-forgotten"},
            source_event_ids=[],
            tactic_id="tactic-racing",
        ),
    )

    assert (await store.get_workbench("session-1"))["temporary_tactics"] == []
    await store.checkpoint_session("session-1")
    restored = L0WorkingMemoryStore(checkpoint_db_path=str(checkpoint_path))
    await restored.initialize()
    assert (await restored.get_workbench("session-1"))["temporary_tactics"] == []


@pytest.mark.asyncio
async def test_l0_forget_active_entities_removes_live_and_checkpoint_state(tmp_path):
    import aiosqlite

    from _shared.memory_schema import apply_memory_shared_schema
    from magi.memory.l0.working_memory import L0WorkingMemoryStore

    checkpoint_path = tmp_path / "l0_active_entity_forget.db"
    await apply_memory_shared_schema(str(checkpoint_path))
    store = L0WorkingMemoryStore(checkpoint_db_path=str(checkpoint_path))
    await store.initialize()
    await store.upsert_active_entity(
        session_id="session-1",
        entity_id="person:delete",
        entity_type="person",
        snapshot={"name": "Delete Me"},
        source_event_ids=["event-delete"],
    )
    await store.upsert_active_entity(
        session_id="session-1",
        entity_id="person:keep",
        entity_type="person",
        snapshot={"name": "Keep Me"},
        source_event_ids=["event-keep"],
    )
    await store.checkpoint_session("session-1")

    assert await store.forget_active_entities(["event-delete"]) == 1
    assert [
        entity["entity_id"]
        for entity in (await store.get_workbench("session-1"))["active_entities"]
    ] == ["person:keep"]
    async with aiosqlite.connect(checkpoint_path) as db:
        async with db.execute(
            "SELECT entity_id FROM l0_active_entities ORDER BY entity_id"
        ) as cursor:
            assert await cursor.fetchall() == [("person:keep",)]

    restored = L0WorkingMemoryStore(checkpoint_db_path=str(checkpoint_path))
    await restored.initialize()
    assert [
        entity["entity_id"]
        for entity in (await restored.get_workbench("session-1"))["active_entities"]
    ] == ["person:keep"]


@pytest.mark.asyncio
async def test_l0_active_entity_reads_and_restore_fail_closed_on_governance(tmp_path):
    import json

    import aiosqlite

    from _shared.memory_schema import apply_memory_shared_schema
    from magi.memory.l0.working_memory import L0WorkingMemoryStore

    checkpoint_path = tmp_path / "l0_active_entity_governance.db"
    await apply_memory_shared_schema(str(checkpoint_path))
    store = L0WorkingMemoryStore(checkpoint_db_path=str(checkpoint_path))
    await store.initialize()
    for entity_id, event_id in (
        ("person:tombstoned", "event-tombstoned"),
        ("person:time", "event-time"),
        ("person:target", "event-shared"),
        ("person:other", "event-shared"),
        ("person:safe", "event-safe"),
    ):
        await store.upsert_active_entity(
            session_id="session-1",
            entity_id=entity_id,
            entity_type="person",
            snapshot={"name": entity_id},
            source_event_ids=[event_id],
        )
    await store.checkpoint_session("session-1")

    async with aiosqlite.connect(checkpoint_path) as db:
        await db.execute("""
            INSERT INTO memory_source_event_tombstones(event_id, reason, created_at)
            VALUES ('event-tombstoned', 'user_delete_event', 1)
            """)
        await db.execute("""
            INSERT INTO memory_forget_operations(
                operation_id, selector_kind, selector_hash, selector_json,
                reason, created_at, updated_at
            ) VALUES ('operation-time', 'time_range', 'hash-time', '{}', 'test', 1, 1)
            """)
        await db.execute("""
            INSERT INTO memory_forget_operations(
                operation_id, selector_kind, selector_hash, selector_json,
                reason, created_at, updated_at
            ) VALUES ('operation-entity', 'entity', 'hash-entity', '{}', 'test', 1, 1)
            """)
        await db.executemany(
            """
            INSERT INTO memory_projection_blocks(
                block_kind, target_id, event_id, operation_id, created_at
            ) VALUES (?, ?, ?, ?, 1)
            """,
            [
                ("episode_formation", "time:hash-time", "event-time", "operation-time"),
                ("entity_projection", "person:target", "event-shared", "operation-entity"),
            ],
        )
        await db.execute(
            """
            INSERT INTO l0_active_entities(
                session_id, entity_id, entity_type, relevance_score,
                snapshot_json, source_event_ids, loaded_at,
                last_accessed_at, access_count
            ) VALUES (?, ?, ?, 0, ?, ?, 1, 1, 1)
            """,
            (
                "session-1",
                "person:malformed",
                "person",
                json.dumps({"name": "must not restore"}),
                "not-json",
            ),
        )
        await db.commit()

    expected = ["person:other", "person:safe"]
    assert (
        sorted(
            entity["entity_id"]
            for entity in (await store.get_workbench("session-1"))["active_entities"]
        )
        == expected
    )

    restored = L0WorkingMemoryStore(checkpoint_db_path=str(checkpoint_path))
    await restored.initialize()
    assert (
        sorted(
            entity["entity_id"]
            for entity in (await restored.get_workbench("session-1"))["active_entities"]
        )
        == expected
    )


@pytest.mark.asyncio
async def test_l0_tactics_reject_time_range_barriers_on_read_write_and_restore(tmp_path):
    import aiosqlite

    from _shared.memory_schema import apply_memory_shared_schema
    from magi.memory.l0.working_memory import L0WorkingMemoryStore

    checkpoint_path = tmp_path / "l0_time_range_tactic_governance.db"
    await apply_memory_shared_schema(str(checkpoint_path))
    store = L0WorkingMemoryStore(checkpoint_db_path=str(checkpoint_path))
    await store.initialize()
    await store.add_temporary_tactic(
        session_id="session-1",
        scope_type="session",
        scope_id="session-1",
        tactic_type="time-backed",
        tactic_payload={},
        source_event_ids=["event-time"],
        tactic_id="tactic-time",
    )
    await store.checkpoint_session("session-1")

    async with aiosqlite.connect(checkpoint_path) as db:
        await db.execute("""
            INSERT INTO memory_forget_operations(
                operation_id, selector_kind, selector_hash, selector_json,
                reason, created_at, updated_at
            ) VALUES ('operation-time-tactic', 'time_range', 'hash-time', '{}', 'test', 1, 1)
            """)
        await db.execute("""
            INSERT INTO memory_projection_blocks(
                block_kind, target_id, event_id, operation_id, created_at
            ) VALUES (
                'episode_formation', 'time:hash-time', 'event-time',
                'operation-time-tactic', 1
            )
            """)
        await db.commit()

    assert (await store.get_workbench("session-1"))["temporary_tactics"] == []
    assert (
        await store.add_temporary_tactic(
            session_id="session-1",
            scope_type="session",
            scope_id="session-1",
            tactic_type="late-time-backed",
            tactic_payload={},
            source_event_ids=["event-time"],
        )
        is None
    )

    restored = L0WorkingMemoryStore(checkpoint_db_path=str(checkpoint_path))
    await restored.initialize()
    assert (await restored.get_workbench("session-1"))["temporary_tactics"] == []
