"""Behavior tests for session-local L0 attention state."""

from __future__ import annotations

import asyncio
import time

import aiosqlite
import pytest

from _shared.memory_schema import apply_memory_shared_schema
from magi.memory.l0.attention import (
    AttentionActionType,
    AttentionEvidenceMode,
    AttentionKind,
    AttentionUpdateAction,
)
from magi.memory.l0.working.workbench import MAX_ATTENTION_ITEMS_PER_SESSION
from magi.memory.l0.working_memory import L0WorkingMemoryStore
from magi.memory.shared_clear import clear_shared_auxiliary_memory
from magi.memory.source_event_governance import upsert_source_turn_cutoffs


def _store(tmp_path, **overrides) -> L0WorkingMemoryStore:
    return L0WorkingMemoryStore(
        checkpoint_db_path=str(tmp_path / "memory.db"),
        checkpoint_interval_seconds=1,
        session_timeout_seconds=overrides.pop("session_timeout_seconds", 3600),
        restore_on_restart=overrides.pop("restore_on_restart", True),
        **overrides,
    )


def _action(
    *,
    action: AttentionActionType = AttentionActionType.ADD,
    target_item_id: str | None = None,
    kind: AttentionKind | None = AttentionKind.FOCUS,
    summary: str | None = "正在讨论 L0 的短期关注设计",
    source_turn_ids: tuple[str, ...] = ("turn-1",),
    source_event_ids: tuple[str, ...] = (),
    entity_id: str | None = None,
    task_id: str | None = None,
    task_attempt: int | None = None,
    evidence_mode: AttentionEvidenceMode = AttentionEvidenceMode.DIRECT,
    salience: float = 0.8,
    confidence: float = 0.9,
) -> AttentionUpdateAction:
    return AttentionUpdateAction(
        action=action,
        target_item_id=target_item_id,
        kind=kind,
        summary=summary,
        source_turn_ids=source_turn_ids,
        source_event_ids=source_event_ids,
        entity_id=entity_id,
        task_id=task_id,
        task_attempt=task_attempt,
        evidence_mode=evidence_mode,
        salience=salience,
        confidence=confidence,
    )


async def _persist_entity_projection_block(
    db_path,
    *,
    event_id: str,
    entity_id: str,
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO memory_forget_operations(
                operation_id, selector_kind, selector_hash, selector_json,
                reason, created_at, updated_at
            ) VALUES (?, 'entity', ?, '{}', 'test_entity_forget', 1, 1)
            """,
            (f"forget-{entity_id}", f"hash-{entity_id}"),
        )
        await db.execute(
            """
            INSERT INTO memory_projection_blocks(
                block_kind, target_id, event_id, operation_id, created_at
            ) VALUES ('entity_projection', ?, ?, ?, 1)
            """,
            (entity_id, event_id, f"forget-{entity_id}"),
        )
        await db.commit()


@pytest.mark.asyncio
async def test_attention_actions_build_and_evolve_frame(tmp_path) -> None:
    store = _store(tmp_path)
    created = await store.apply_attention_actions(
        session_id="session-1",
        actions=[_action()],
        expected_revision=0,
        last_processed_turn_id="turn-1",
        source_texts=["我们来聊聊 L0"],
    )

    assert created is not None
    assert created["revision"] == 1
    item = created["items"][0]
    assert item["kind"] == "focus"
    assert item["status"] == "active"
    assert item["source_turn_ids"] == ["turn-1"]
    item_id = item["item_id"]

    reinforced = await store.apply_attention_actions(
        session_id="session-1",
        actions=[
            _action(
                action=AttentionActionType.REINFORCE,
                target_item_id=item_id,
                kind=None,
                summary="进一步确认 L0 应服务于自然续聊",
                source_turn_ids=("turn-2",),
                salience=0.95,
            )
        ],
        expected_revision=1,
        last_processed_turn_id="turn-2",
    )
    assert reinforced is not None
    assert reinforced["items"][0]["summary"] == "进一步确认 L0 应服务于自然续聊"
    assert reinforced["items"][0]["source_turn_ids"] == ["turn-1", "turn-2"]

    backgrounded = await store.apply_attention_actions(
        session_id="session-1",
        actions=[
            _action(
                action=AttentionActionType.BACKGROUND,
                target_item_id=item_id,
                kind=None,
                summary=None,
                source_turn_ids=("turn-3",),
            )
        ],
        expected_revision=2,
        last_processed_turn_id="turn-3",
    )
    assert backgrounded is not None
    assert backgrounded["items"][0]["status"] == "background"
    assert backgrounded["items"][0]["source_turn_ids"] == [
        "turn-1",
        "turn-2",
        "turn-3",
    ]

    resolved = await store.apply_attention_actions(
        session_id="session-1",
        actions=[
            _action(
                action=AttentionActionType.RESOLVE,
                target_item_id=item_id,
                kind=None,
                summary=None,
                source_turn_ids=("turn-4",),
            )
        ],
        expected_revision=3,
        last_processed_turn_id="turn-4",
    )
    assert resolved is not None
    assert resolved["items"][0]["status"] == "resolved"
    await store.shutdown()


@pytest.mark.asyncio
async def test_supersede_keeps_lineage_and_creates_replacement(tmp_path) -> None:
    store = _store(tmp_path)
    initial = await store.apply_attention_actions(
        session_id="session-1",
        actions=[_action()],
        expected_revision=0,
        last_processed_turn_id="turn-1",
    )
    old_id = initial["items"][0]["item_id"]

    result = await store.apply_attention_actions(
        session_id="session-1",
        actions=[
            _action(
                action=AttentionActionType.SUPERSEDE,
                target_item_id=old_id,
                kind=AttentionKind.CONSENSUS,
                summary="已确认 L0 是会话关注投影",
                source_turn_ids=("turn-2",),
            )
        ],
        expected_revision=1,
        last_processed_turn_id="turn-2",
    )

    assert result is not None
    by_status = {item["status"]: item for item in result["items"]}
    assert by_status["superseded"]["item_id"] == old_id
    assert by_status["active"]["supersedes_item_id"] == old_id
    assert by_status["active"]["kind"] == "consensus"
    assert "turn-2" in by_status["superseded"]["source_turn_ids"]
    assert "turn-2" in by_status["active"]["source_turn_ids"]
    assert await store.forget_chat_turn(
        session_id="session-1",
        turn_id="turn-2",
    ) == 2
    assert (await store.get_attention_snapshot("session-1"))["items"] == []
    await store.shutdown()


@pytest.mark.asyncio
async def test_stale_revision_does_not_overwrite_newer_attention(tmp_path) -> None:
    store = _store(tmp_path)
    await store.apply_attention_actions(
        session_id="session-1",
        actions=[_action()],
        expected_revision=0,
        last_processed_turn_id="turn-1",
    )

    before = await store.get_attention_snapshot("session-1")

    stale = await store.apply_attention_actions(
        session_id="session-1",
        actions=[
            _action(
                kind=AttentionKind.OPEN_LOOP,
                summary="待确认的旧批次",
                source_turn_ids=("turn-stale",),
            )
        ],
        expected_revision=0,
        last_processed_turn_id="turn-stale",
    )

    assert stale is None
    snapshot = await store.get_attention_snapshot("session-1")
    assert snapshot["revision"] == 1
    assert snapshot["last_processed_turn_id"] == "turn-1"
    assert len(snapshot["items"]) == 1
    assert snapshot == before
    await store.shutdown()


@pytest.mark.asyncio
async def test_raw_source_copy_is_rejected_but_frontier_advances(tmp_path) -> None:
    store = _store(tmp_path)
    source_text = "我今天心情不好"
    result = await store.apply_attention_actions(
        session_id="session-1",
        actions=[
            _action(
                kind=AttentionKind.SITUATION,
                summary=source_text,
            )
        ],
        expected_revision=0,
        last_processed_turn_id="turn-1",
        source_texts=[source_text],
    )

    assert result is not None
    assert result["revision"] == 1
    assert result["items"] == []
    await store.shutdown()


@pytest.mark.asyncio
async def test_prompt_projection_independently_enforces_trust_and_activity(tmp_path):
    store = _store(tmp_path)
    try:
        created = await store.apply_attention_actions(
            session_id="session-1",
            actions=[
                _action(summary="可信的活跃关注"),
                _action(
                    summary="低可信的活跃推测",
                    evidence_mode=AttentionEvidenceMode.INFERRED,
                    confidence=0.6,
                ),
                _action(summary="可信但暂时后台的话题"),
            ],
            expected_revision=0,
            last_processed_turn_id="turn-1",
        )
        assert len(created["items"]) == 3
        background = next(
            item for item in created["items"] if item["summary"] == "可信但暂时后台的话题"
        )
        await store.apply_attention_actions(
            session_id="session-1",
            actions=[
                _action(
                    action=AttentionActionType.BACKGROUND,
                    target_item_id=background["item_id"],
                    kind=None,
                    summary=None,
                )
            ],
            expected_revision=1,
            last_processed_turn_id="turn-2",
        )
        snapshot = await store.get_attention_snapshot("session-1")
        assert {item["summary"]: item["status"] for item in snapshot["items"]} == {
            "可信的活跃关注": "active",
            "低可信的活跃推测": "active",
            "可信但暂时后台的话题": "background",
        }
        projection = await store.get_prompt_workbench_projection("session-1")
        assert [item["summary"] for item in projection.attention_items] == ["可信的活跃关注"]
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_prompt_projection_reactivates_only_relevant_background_attention(
    tmp_path,
) -> None:
    store = _store(tmp_path)
    created = await store.apply_attention_actions(
        session_id="session-1",
        actions=[
            _action(
                kind=AttentionKind.OPEN_LOOP,
                summary="还没有聊完新专辑里的海浪音色",
                source_turn_ids=("turn-1",),
            ),
            _action(
                kind=AttentionKind.OPEN_LOOP,
                summary="另一个待续话题是上海旅行",
                source_turn_ids=("turn-1",),
            ),
        ],
        expected_revision=0,
        last_processed_turn_id="turn-1",
    )
    await store.apply_attention_actions(
        session_id="session-1",
        actions=[
            _action(
                action=AttentionActionType.BACKGROUND,
                target_item_id=item["item_id"],
                kind=None,
                summary=None,
                source_turn_ids=("turn-2",),
            )
            for item in created["items"]
        ],
        expected_revision=1,
        last_processed_turn_id="turn-2",
    )

    projection = await store.get_prompt_workbench_projection(
        "session-1",
        query="我们继续说那张新专辑吧",
    )

    assert [item["summary"] for item in projection.attention_items] == [
        "还没有聊完新专辑里的海浪音色"
    ]
    assert projection.attention_items[0]["status"] == "background"
    await store.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("priority", ["status", "salience", "recency"])
async def test_attention_capacity_evicts_exact_lowest_priority_item(tmp_path, priority):
    store = _store(tmp_path)
    try:
        created = await store.apply_attention_actions(
            session_id="session-1",
            actions=[
                _action(
                    kind=AttentionKind.ACTIVE_OBJECT,
                    summary=f"关注对象 {index}",
                    source_turn_ids=(f"turn-{index}",),
                    salience=0.9,
                )
                for index in range(MAX_ATTENTION_ITEMS_PER_SESSION)
            ],
            expected_revision=0,
            last_processed_turn_id="turn-seed",
        )
        by_summary = {item["summary"]: item["item_id"] for item in created["items"]}
        victim = by_summary["关注对象 7"]
        now = time.time()
        for item in store._attention_items["session-1"].values():
            item["last_reinforced_at"] = now - 20
        target = store._attention_items["session-1"][victim]
        if priority == "status":
            target.update(status="background", salience=1.0, last_reinforced_at=now)
        elif priority == "salience":
            target.update(salience=0.05, last_reinforced_at=now)
        else:
            target["last_reinforced_at"] = now - 100
        result = await store.apply_attention_actions(
            session_id="session-1",
            actions=[
                _action(
                    kind=AttentionKind.ACTIVE_OBJECT,
                    summary="新加入的关注",
                    source_turn_ids=("turn-new",),
                    salience=0.1 if priority != "recency" else 0.9,
                )
            ],
            expected_revision=1,
            last_processed_turn_id="turn-new",
        )
        actual = {item["summary"]: item["item_id"] for item in result["items"]}
        assert set(actual) == (set(by_summary) - {"关注对象 7"}) | {"新加入的关注"}
        assert {key: value for key, value in actual.items() if key != "新加入的关注"} == {
            key: value for key, value in by_summary.items() if key != "关注对象 7"
        }
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_checkpoint_restore_preserves_attention_and_revision(tmp_path) -> None:
    store = _store(tmp_path)
    await store.apply_attention_actions(
        session_id="session-1",
        actions=[_action(entity_id="project:magi")],
        expected_revision=0,
        last_processed_turn_id="turn-1",
    )
    await store.checkpoint_all()
    await store.shutdown()

    restored = _store(tmp_path)
    await restored.initialize()
    snapshot = await restored.get_attention_snapshot("session-1")

    assert snapshot["revision"] == 1
    assert snapshot["last_processed_turn_id"] == "turn-1"
    assert snapshot["items"][0]["entity_id"] == "project:magi"
    await restored.shutdown()


@pytest.mark.asyncio
async def test_source_forgetting_removes_and_blocks_replay(tmp_path) -> None:
    store = _store(tmp_path)
    await store.apply_attention_actions(
        session_id="session-1",
        actions=[
            _action(
                source_turn_ids=("turn-forgotten",),
                source_event_ids=("event-forgotten",),
            )
        ],
        expected_revision=0,
        last_processed_turn_id="turn-forgotten",
    )
    await store.checkpoint_all()

    assert await store.forget_attention_items(["event-forgotten"]) == 1
    replay = await store.apply_attention_actions(
        session_id="session-1",
        actions=[
            _action(
                summary="不应从已忘记来源恢复",
                source_turn_ids=("turn-2",),
                source_event_ids=("event-forgotten",),
            )
        ],
        expected_revision=1,
        last_processed_turn_id="turn-2",
    )
    assert replay is not None
    assert replay["items"] == []

    await store.checkpoint_all()
    await store.shutdown()
    restored = _store(tmp_path)
    await restored.initialize()
    assert (await restored.get_workbench("session-1"))["attention_items"] == []
    await restored.shutdown()


@pytest.mark.asyncio
async def test_legacy_permanent_turn_reference_still_blocks_replay(
    tmp_path,
) -> None:
    store = _store(tmp_path)
    assert await store.forget_attention_items(["turn-legacy-forgotten"]) == 0

    replay = await store.apply_attention_actions(
        session_id="session-1",
        actions=[
            _action(
                source_turn_ids=("turn-legacy-forgotten",),
            )
        ],
        expected_revision=0,
        last_processed_turn_id="turn-legacy-forgotten",
        source_turn_accepted_at={
            "turn-legacy-forgotten": time.time() + 100,
        },
    )
    assert replay is not None
    assert replay["items"] == []
    await store.shutdown()


@pytest.mark.asyncio
async def test_entity_projection_barrier_blocks_write_read_and_restart(
    tmp_path,
) -> None:
    db_path = tmp_path / "memory.db"
    await apply_memory_shared_schema(str(db_path))
    store = _store(tmp_path)
    await store.apply_attention_actions(
        session_id="session-1",
        actions=[
            _action(
                summary="正在讨论应被遗忘的人",
                source_turn_ids=("turn-old",),
                source_event_ids=("event-entity",),
                entity_id="person:forgotten",
            )
        ],
        expected_revision=0,
        last_processed_turn_id="turn-old",
    )
    await store.checkpoint_all()
    await _persist_entity_projection_block(
        db_path,
        event_id="event-entity",
        entity_id="person:forgotten",
    )

    assert (await store.get_workbench("session-1"))["attention_items"] == []
    assert (
        await store.get_session_index_snapshot()
    )["attention_by_session"]["session-1"] == {}
    result = await store.apply_attention_actions(
        session_id="session-1",
        actions=[
            _action(
                summary="旧来源不应重新生成关注",
                source_turn_ids=("turn-late",),
                source_event_ids=("event-entity",),
                entity_id="person:forgotten",
            )
        ],
        expected_revision=1,
        last_processed_turn_id="turn-late",
    )
    assert result is not None
    await store.checkpoint_all()
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM l0_attention_items"
        ) as cursor:
            assert (await cursor.fetchone())[0] == 1

    await store.shutdown()
    restored = _store(tmp_path)
    await restored.initialize()
    assert (await restored.get_workbench("session-1"))["attention_items"] == []
    await restored.shutdown()


@pytest.mark.asyncio
async def test_clear_removes_attention_and_resets_turn_and_entity_barriers(tmp_path):
    store = _store(tmp_path)
    try:
        seeded = await store.apply_attention_actions(
            session_id="session-1",
            actions=[_action(summary="清理前的关注", source_turn_ids=("turn-seed",))],
            expected_revision=0,
            last_processed_turn_id="turn-seed",
        )
        assert len(seeded["items"]) == 1
        await store.forget_attention_items(["turn-1"])
        cutoff_at = time.time()
        await store.forget_entity(
            "person:forgotten", forgotten_at=cutoff_at, operation_id="forget-person"
        )
        actions = [
            _action(summary="来自已遗忘轮次", source_turn_ids=("turn-1",)),
            _action(
                summary="来自已遗忘实体", source_turn_ids=("turn-2",), entity_id="person:forgotten"
            ),
        ]
        before = await store.get_attention_snapshot("session-1")
        blocked = await store.apply_attention_actions(
            session_id="session-1",
            actions=actions,
            expected_revision=before["revision"],
            last_processed_turn_id="turn-blocked",
            source_turn_accepted_at={"turn-1": cutoff_at - 1, "turn-2": cutoff_at - 1},
        )
        assert [item["summary"] for item in blocked["items"]] == ["清理前的关注"]
        await store.clear()
        assert (await store.get_attention_snapshot("session-1"))["items"] == []
        result = await store.apply_attention_actions(
            session_id="session-1",
            actions=actions,
            expected_revision=0,
            last_processed_turn_id="turn-replay",
            source_turn_accepted_at={"turn-1": cutoff_at - 1, "turn-2": cutoff_at - 1},
        )
        assert {item["summary"] for item in result["items"]} == {"来自已遗忘轮次", "来自已遗忘实体"}
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_turn_cutoff_blocks_old_attempt_but_allows_new_delivery(
    tmp_path,
) -> None:
    store = _store(tmp_path)
    old_accepted_at = time.time()
    created = await store.apply_attention_actions(
        session_id="session-1",
        actions=[_action(source_turn_ids=("turn-replayed",))],
        expected_revision=0,
        last_processed_turn_id="turn-replayed",
        source_turn_accepted_at={"turn-replayed": old_accepted_at},
    )
    assert created is not None and len(created["items"]) == 1

    assert await store.forget_chat_turn(
        session_id="session-1",
        turn_id="turn-replayed",
    ) == 1
    stale = await store.apply_attention_actions(
        session_id="session-1",
        actions=[
            _action(
                summary="旧投递不应恢复",
                source_turn_ids=("turn-replayed",),
            )
        ],
        expected_revision=1,
        last_processed_turn_id="turn-replayed",
        source_turn_accepted_at={"turn-replayed": old_accepted_at},
    )
    assert stale is not None and stale["items"] == []

    fresh_accepted_at = time.time() + 1
    fresh = await store.apply_attention_actions(
        session_id="session-1",
        actions=[
            _action(
                summary="删除后的新投递可以重新形成关注",
                source_turn_ids=("turn-replayed",),
            )
        ],
        expected_revision=2,
        last_processed_turn_id="turn-replayed",
        source_turn_accepted_at={"turn-replayed": fresh_accepted_at},
    )
    assert fresh is not None and len(fresh["items"]) == 1
    await store.shutdown()


@pytest.mark.asyncio
async def test_task_lifecycle_update_preserves_original_turn_time_and_cannot_revive(
    tmp_path,
) -> None:
    store = _store(tmp_path)
    original_accepted_at = time.time() - 10
    created = await store.apply_attention_actions(
        session_id="session-1",
        actions=[
            _action(
                kind=AttentionKind.OPEN_LOOP,
                source_turn_ids=("turn-task-origin",),
                task_id="task-1",
                task_attempt=0,
            )
        ],
        expected_revision=0,
        last_processed_turn_id="turn-task-origin",
        source_turn_accepted_at={
            "turn-task-origin": original_accepted_at,
        },
    )
    assert created is not None
    item_id = created["items"][0]["item_id"]

    reopened = await store.apply_attention_actions(
        session_id="session-1",
        actions=[
            _action(
                action=AttentionActionType.REINFORCE,
                target_item_id=item_id,
                kind=None,
                summary=None,
                source_turn_ids=(),
                task_id="task-1",
                task_attempt=1,
            )
        ],
        expected_revision=1,
        last_processed_turn_id="task-attempt-1",
        source_turn_accepted_at={},
    )
    assert reopened is not None
    live_item = store._attention_items["session-1"][item_id]
    assert live_item["metadata"]["source_turn_accepted_at"] == {
        "turn-task-origin": original_accepted_at,
    }

    forget_cutoff = original_accepted_at + 5
    async with aiosqlite.connect(tmp_path / "memory.db") as db:
        await upsert_source_turn_cutoffs(
            db,
            turn_ids=("turn-task-origin",),
            cutoff_at=forget_cutoff,
            reason="test_delayed_forget_page",
        )
        await db.commit()

    assert (await store.get_attention_snapshot("session-1"))["items"] == []
    blocked = await store.apply_attention_actions(
        session_id="session-1",
        actions=[
            _action(
                action=AttentionActionType.REINFORCE,
                target_item_id=item_id,
                kind=None,
                summary=None,
                source_turn_ids=(),
                task_id="task-1",
                task_attempt=2,
            )
        ],
        expected_revision=2,
        last_processed_turn_id="task-attempt-2",
        source_turn_accepted_at={},
    )
    assert blocked is not None
    live_item = store._attention_items["session-1"][item_id]
    assert live_item["task_attempt"] == 1
    assert live_item["metadata"]["source_turn_accepted_at"] == {
        "turn-task-origin": original_accepted_at,
    }
    assert (await store.get_attention_snapshot("session-1"))["items"] == []
    await store.shutdown()


@pytest.mark.asyncio
async def test_layer_clear_preserves_turn_cutoff_until_full_memory_clear(
    tmp_path,
) -> None:
    store = _store(tmp_path)
    await store.forget_chat_turn(
        session_id="session-1",
        turn_id="turn-forgotten",
    )
    await store.clear()
    async with aiosqlite.connect(tmp_path / "memory.db") as db:
        async with db.execute(
            "SELECT turn_id FROM memory_source_turn_cutoffs"
        ) as cursor:
            assert await cursor.fetchall() == [("turn-forgotten",)]

    await clear_shared_auxiliary_memory(str(tmp_path / "memory.db"))
    async with aiosqlite.connect(tmp_path / "memory.db") as db:
        async with db.execute(
            "SELECT turn_id FROM memory_source_turn_cutoffs"
        ) as cursor:
            assert await cursor.fetchall() == []
    await store.shutdown()


@pytest.mark.asyncio
async def test_forget_entity_removes_linked_attention_only(tmp_path) -> None:
    store = _store(tmp_path)
    await store.apply_attention_actions(
        session_id="session-1",
        actions=[
            _action(
                summary="正在讨论 Magi",
                entity_id="project:magi",
                source_turn_ids=("turn-1",),
            ),
            _action(
                summary="同时提到另一项目",
                entity_id="project:other",
                source_turn_ids=("turn-1",),
            ),
        ],
        expected_revision=0,
        last_processed_turn_id="turn-1",
    )
    await store.checkpoint_all()

    assert await store.forget_entity("project:magi") == 1
    assert [
        item["entity_id"]
        for item in (await store.get_workbench("session-1"))["attention_items"]
    ] == ["project:other"]
    await store.shutdown()


@pytest.mark.asyncio
async def test_forget_entity_rejects_in_flight_analysis_from_old_revision(
    tmp_path,
) -> None:
    store = _store(tmp_path)
    await store.initialize()
    await store.start_session(session_id="session-1")
    analysis_started = asyncio.Event()
    allow_apply = asyncio.Event()
    cutoff_at = time.time()

    async def apply_in_flight_analysis():
        snapshot = await store.get_attention_snapshot("session-1")
        analysis_started.set()
        await allow_apply.wait()
        return await store.apply_attention_actions(
            session_id="session-1",
            actions=[
                _action(
                    summary="旧分析试图重新加入已遗忘的人",
                    source_turn_ids=("turn-in-flight",),
                    entity_id="person:forgotten",
                )
            ],
            expected_revision=int(snapshot["revision"]),
            last_processed_turn_id="turn-in-flight",
            source_turn_accepted_at={"turn-in-flight": cutoff_at - 1},
        )

    analysis_task = asyncio.create_task(apply_in_flight_analysis())
    await analysis_started.wait()
    assert await store.forget_entity(
        "person:forgotten",
        forgotten_at=cutoff_at,
        operation_id="forget-person",
    ) == 0
    allow_apply.set()

    assert await analysis_task is None
    after_forget = await store.get_attention_snapshot("session-1")
    assert after_forget["revision"] == 1
    assert after_forget["last_processed_turn_id"] is None
    assert after_forget["items"] == []

    fresh = await store.apply_attention_actions(
        session_id="session-1",
        actions=[
            _action(
                summary="遗忘操作之后的新对话重新提到了这个人",
                source_turn_ids=("turn-after-forget",),
                entity_id="person:forgotten",
            )
        ],
        expected_revision=1,
        last_processed_turn_id="turn-after-forget",
        source_turn_accepted_at={"turn-after-forget": cutoff_at + 1},
    )
    assert fresh is not None
    assert [item["entity_id"] for item in fresh["items"]] == [
        "person:forgotten"
    ]
    await store.shutdown()


@pytest.mark.asyncio
async def test_forget_entity_uses_source_turn_time_not_late_write_time(
    tmp_path,
) -> None:
    store = _store(tmp_path)
    cutoff_at = time.time()
    written_late = await store.apply_attention_actions(
        session_id="session-1",
        actions=[
            _action(
                summary="旧轮次在遗忘请求后才完成分析",
                source_turn_ids=("turn-before-forget",),
                entity_id="person:forgotten",
            )
        ],
        expected_revision=0,
        last_processed_turn_id="turn-before-forget",
        source_turn_accepted_at={"turn-before-forget": cutoff_at - 1},
    )
    assert written_late is not None
    assert len(written_late["items"]) == 1

    assert await store.forget_entity(
        "person:forgotten",
        forgotten_at=cutoff_at,
        operation_id="forget-person",
    ) == 1
    assert (await store.get_attention_snapshot("session-1"))["items"] == []

    new_dialogue = await store.apply_attention_actions(
        session_id="session-1",
        actions=[
            _action(
                summary="遗忘完成后的新轮次重新提到了这个人",
                source_turn_ids=("turn-after-forget",),
                entity_id="person:forgotten",
            )
        ],
        expected_revision=2,
        last_processed_turn_id="turn-after-forget",
        source_turn_accepted_at={"turn-after-forget": cutoff_at + 1},
    )
    assert new_dialogue is not None
    assert [item["entity_id"] for item in new_dialogue["items"]] == [
        "person:forgotten"
    ]
    await store.shutdown()


@pytest.mark.asyncio
async def test_entity_forget_cutoff_survives_restart_without_tombstoning_new_turns(
    tmp_path,
) -> None:
    cutoff_at = time.time()
    store = _store(tmp_path)
    await store.forget_entity(
        "person:forgotten",
        forgotten_at=cutoff_at,
        operation_id="forget-person",
    )
    await store.shutdown()

    restored = _store(tmp_path)
    stale = await restored.apply_attention_actions(
        session_id="session-1",
        actions=[
            _action(
                summary="重启后的旧轮次不应恢复关注",
                source_turn_ids=("turn-before-forget",),
                entity_id="person:forgotten",
            )
        ],
        expected_revision=0,
        last_processed_turn_id="turn-before-forget",
        source_turn_accepted_at={"turn-before-forget": cutoff_at - 1},
    )
    assert stale is not None
    assert stale["items"] == []

    fresh = await restored.apply_attention_actions(
        session_id="session-1",
        actions=[
            _action(
                summary="重启后的新轮次可以重新形成关注",
                source_turn_ids=("turn-after-forget",),
                entity_id="person:forgotten",
            )
        ],
        expected_revision=1,
        last_processed_turn_id="turn-after-forget",
        source_turn_accepted_at={"turn-after-forget": cutoff_at + 1},
    )
    assert fresh is not None
    assert [item["entity_id"] for item in fresh["items"]] == [
        "person:forgotten"
    ]
    await restored.checkpoint_all()
    await restored.shutdown()

    checked = _store(tmp_path)
    assert [
        item["entity_id"]
        for item in (await checked.get_attention_snapshot("session-1"))["items"]
    ] == ["person:forgotten"]
    await checked.shutdown()


@pytest.mark.asyncio
async def test_idle_session_survives_while_attention_is_live_then_expires(tmp_path) -> None:
    store = _store(tmp_path, session_timeout_seconds=1)
    await store.apply_attention_actions(
        session_id="session-1",
        actions=[_action()],
        expected_revision=0,
        last_processed_turn_id="turn-1",
    )
    store._sessions["session-1"]["last_active_at"] = time.time() - 10

    assert await store.expire_idle_sessions() == []
    store._attention_items["session-1"][next(iter(store._attention_items["session-1"]))][
        "expires_at"
    ] = time.time() - 1
    assert await store.expire_idle_sessions() == ["session-1"]
    assert (await store.get_workbench("session-1"))["session"] is None
    await store.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("capacity,count", [(1, 2), (64, 100)])
async def test_concurrent_session_capacity_preserves_exact_owner_and_attention(
    tmp_path, capacity, count
):
    store = _store(tmp_path, max_concurrent_sessions=capacity)
    try:
        await store.initialize()
        results = await asyncio.gather(
            *(
                store.apply_attention_actions(
                    session_id=f"session-{index}",
                    user_id=f"user-{index}",
                    actions=[
                        _action(summary=f"关注内容 {index}", source_turn_ids=(f"turn-{index}",))
                    ],
                    expected_revision=0,
                    last_processed_turn_id=f"turn-{index}",
                )
                for index in range(count)
            )
        )
        assert all(result is not None for result in results)
        assert len(store._sessions) == capacity
        assert set(store._sessions) == set(store._attention_items)
        for session_id, session in store._sessions.items():
            index = int(session_id.removeprefix("session-"))
            assert session["user_id"] == f"user-{index}"
            assert session["metadata"]["last_processed_turn_id"] == f"turn-{index}"
            items = list(store._attention_items[session_id].values())
            assert len(items) == 1
            assert items[0]["summary"] == f"关注内容 {index}"
            assert items[0]["source_turn_ids"] == [f"turn-{index}"]
            assert items[0]["item_id"] == results[index]["items"][0]["item_id"]
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_reactivation_and_expiry_preserve_existing_attention_and_session_metadata(tmp_path):
    from copy import deepcopy

    store = _store(tmp_path, session_timeout_seconds=1)
    try:
        await store.apply_attention_actions(
            session_id="session-1",
            actions=[_action(summary="必须保留的关注")],
            expected_revision=0,
            last_processed_turn_id="turn-1",
        )
        await store.start_session(session_id="session-1", metadata={"custom": "retained"})
        before = deepcopy(store._attention_items["session-1"])
        original = store._sessions["session-1"]
        original["last_active_at"] = time.time() - 10
        entered = {name: asyncio.Event() for name in ["reactivate", "expire"]}

        class ObservedLock(asyncio.Lock):
            async def acquire(self):
                name = asyncio.current_task().get_name()
                if name in entered:
                    entered[name].set()
                return await super().acquire()

        lock = ObservedLock()
        store._checkpoint_lock = lock
        await lock.acquire()
        reactivate = asyncio.create_task(
            store.start_session(session_id="session-1", user_id="user-1"), name="reactivate"
        )
        await asyncio.wait_for(entered["reactivate"].wait(), 2)
        expiry = asyncio.create_task(store.expire_idle_sessions(), name="expire")
        await asyncio.wait_for(entered["expire"].wait(), 2)
        lock.release()
        session, expired = await asyncio.wait_for(asyncio.gather(reactivate, expiry), 2)
        assert expired == []
        assert session is original
        assert session["user_id"] == "user-1"
        assert session["metadata"]["custom"] == "retained"
        assert store._attention_items["session-1"] == before
        assert (await store.get_attention_snapshot("session-1"))["items"] == list(before.values())
    finally:
        await store.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("forget_first", [False, True])
async def test_concurrent_forget_and_apply_cannot_leave_blocked_attention(tmp_path, forget_first):
    store = _store(tmp_path)
    try:
        await store.initialize()
        apply = store.apply_attention_actions(
            session_id="session-1",
            actions=[_action(source_turn_ids=("turn-forgotten",))],
            expected_revision=0,
            last_processed_turn_id="turn-forgotten",
        )
        forget = store.forget_attention_items(["turn-forgotten"])
        await asyncio.gather(*([forget, apply] if forget_first else [apply, forget]))
        assert store._attention_items.get("session-1", {}) == {}
        assert (await store.get_workbench("session-1"))["attention_items"] == []
        await store.checkpoint_all()
        async with aiosqlite.connect(store.checkpoint_db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM l0_attention_items WHERE session_id='session-1'"
            ) as cursor:
                assert (await cursor.fetchone())[0] == 0
    finally:
        await store.shutdown()
