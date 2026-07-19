import asyncio
import sqlite3
from types import SimpleNamespace

import pytest
from magi.agent.background import (
    BackgroundTask,
    BackgroundTaskEvent,
    BackgroundTaskSpec,
    BackgroundTaskStatus,
    BackgroundTaskStore,
    BackgroundTaskTriggerSource,
)
from magi.agent.background.executor import BackgroundTaskRunResult
from magi.agent.background.manager import BackgroundTaskManager
from magi.outreach.contracts import OutreachKind, Urgency
from magi.outreach.identity import canonical_intent_json
from magi.outreach.producers.background_completion import (
    build_background_completion_producer, task_to_intent,
)
from magi.outreach.schedule import build_outbox_drain_handler


def _task(
    status,
    *,
    trigger=BackgroundTaskTriggerSource.USER,
    summary="done",
    error="",
    attempt_index=0,
    pending_message_id=None,
    origin_turn_id="t1",
):
    spec = BackgroundTaskSpec(user_id="u1", session_id="s1", origin_turn_id=origin_turn_id,
                              title="Find flights", goal="g", selected_tools=[],
                              trigger_source=trigger,
                              pending_message_id=pending_message_id)
    task = BackgroundTask.new(spec)
    task.status = status
    task.summary = summary
    task.error = error
    task.attempt_index = attempt_index
    task.finished_at = 1_700_000.0
    return task


def test_succeeded_maps_to_completed_high_urgency():
    intent = task_to_intent(_task(BackgroundTaskStatus.SUCCEEDED))
    assert intent.kind is OutreachKind.TASK_COMPLETED
    assert intent.facts == "done"
    assert intent.urgency is Urgency.HIGH          # USER trigger
    assert intent.completed_at_ms == 1_700_000_000
    assert intent.origin_turn_id == "t1"
    assert intent.payload["background_task_status"] == "succeeded"


def test_succeeded_carries_durable_code_delegation_references():
    task = _task(BackgroundTaskStatus.SUCCEEDED)
    task.result_payload = {
        "message_payload": {
            "code_agent_delegations": [
                {
                    "delegation_id": "d" * 32,
                    "turn_id": "t1",
                    "workspace_path": "/workspace-at-execution",
                },
                {
                    "delegation_id": "d" * 32,
                    "turn_id": "t1",
                    "workspace_path": "/workspace-at-execution",
                },
                {"delegation_id": "", "turn_id": "t1", "workspace_path": "/bad"},
            ]
        }
    }

    intent = task_to_intent(task)

    assert intent is not None
    assert intent.payload["code_agent_delegations"] == [
        {
            "delegation_id": "d" * 32,
            "turn_id": "t1",
            "workspace_path": "/workspace-at-execution",
        }
    ]


def test_failed_maps_to_failed():
    intent = task_to_intent(_task(BackgroundTaskStatus.FAILED, summary="", error="boom"))
    assert intent.kind is OutreachKind.TASK_FAILED and intent.facts == "boom"


def test_retry_attempts_have_distinct_stable_delivery_identities():
    task = _task(
        BackgroundTaskStatus.FAILED,
        summary="",
        error="boom",
        attempt_index=0,
        pending_message_id="pending-task",
    )
    failed = task_to_intent(task)

    task.status = BackgroundTaskStatus.SUCCEEDED
    task.summary = "done"
    task.error = None
    task.attempt_index = 1
    retried = task_to_intent(task)
    repeated_retry = task_to_intent(task)

    assert failed is not None
    assert retried is not None
    assert repeated_retry is not None
    assert failed.correlation_id != retried.correlation_id
    assert retried.correlation_id == repeated_retry.correlation_id
    assert failed.pending_message_id == "pending-task"
    assert retried.pending_message_id is None


def test_rule_trigger_is_normal_urgency():
    intent = task_to_intent(_task(BackgroundTaskStatus.SUCCEEDED, trigger=BackgroundTaskTriggerSource.RULE))
    assert intent.urgency is Urgency.NORMAL


def test_missing_session_returns_none():
    spec = BackgroundTaskSpec(user_id="", session_id="", origin_turn_id="t", title="x", goal="g")
    task = BackgroundTask.new(spec)
    task.status = BackgroundTaskStatus.SUCCEEDED
    assert task_to_intent(task) is None


@pytest.mark.asyncio
async def test_producer_submits_intent():
    submitted = []

    class _Svc:
        async def submit(self, intent): submitted.append(intent)

    producer = build_background_completion_producer(_Svc())
    await producer(_task(BackgroundTaskStatus.SUCCEEDED))
    assert len(submitted) == 1 and submitted[0].correlation_id


async def _persist_terminal_task(
    store: BackgroundTaskStore,
    *,
    attempt_index: int = 0,
    status: BackgroundTaskStatus = BackgroundTaskStatus.SUCCEEDED,
    origin_turn_id: str = "t1",
) -> BackgroundTask:
    task = _task(
        status,
        attempt_index=attempt_index,
        origin_turn_id=origin_turn_id,
    )
    task.status = BackgroundTaskStatus.RUNNING
    await store.create_task(task)
    previous = task.status
    task.status = status
    if status is BackgroundTaskStatus.FAILED:
        task.summary = None
        task.error = "failed"
    task.updated_at = task.finished_at or task.updated_at
    await store.persist_terminal_transition(
        task,
        BackgroundTaskEvent.transition(
            task_id=task.task_id,
            attempt_index=task.attempt_index,
            from_status=previous,
            to_status=status,
        ),
    )
    return task


@pytest.mark.asyncio
async def test_pending_completion_retries_with_one_composition_and_scrubs_success(
    runtime_paths_with_schema,
):
    store = BackgroundTaskStore(
        db_path=str(runtime_paths_with_schema.background_tasks_db_path)
    )
    task = await _persist_terminal_task(store)

    class _RetryingService:
        def __init__(self):
            self.calls = 0
            self.compose_calls = 0
            self.bodies = []

        async def submit(
            self,
            intent,
            *,
            prepared_body=None,
            persist_composed_body=None,
        ):
            self.calls += 1
            body = prepared_body
            if body is None:
                self.compose_calls += 1
                body = "voice generated once"
                assert persist_composed_body is not None
                await persist_composed_body(body)
            self.bodies.append((intent.correlation_id, body))
            if self.calls == 1:
                raise RuntimeError("desktop unavailable")

    service = _RetryingService()
    producer = build_background_completion_producer(
        service,
        completion_store=store,
    )

    with pytest.raises(RuntimeError, match="desktop unavailable"):
        await producer(task)
    assert await store.count_pending_completion_intents() == 1

    class _Outbox:
        def __init__(self):
            self.calls = 0

        async def drain_due(self, *, now_ms):
            assert now_ms == 4242
            self.calls += 1

    outbox = _Outbox()
    handler = build_outbox_drain_handler(
        outbox,
        producer,
        now_ms=lambda: 4242,
    )
    result = await handler(object())

    assert service.calls == 2
    assert service.compose_calls == 1
    assert result.success is True
    assert result.stats == {"background_completions": 1}
    assert outbox.calls == 1
    assert service.bodies == [
        (f"{task.task_id}:attempt:0", "voice generated once"),
        (f"{task.task_id}:attempt:0", "voice generated once"),
    ]
    assert await store.count_pending_completion_intents() == 0
    with sqlite3.connect(store.db_path) as connection:
        row = connection.execute(
            """
            SELECT state, task_json, intent_json, composed_body, handled_at
            FROM background_task_completion_intents
            WHERE task_id = ? AND attempt_index = 0
            """,
            (task.task_id,),
        ).fetchone()
    assert row is not None
    assert row[:4] == ("handled", "{}", None, None)
    assert row[4] is not None


@pytest.mark.asyncio
async def test_startup_drain_delivers_completion_created_before_listener(
    runtime_paths_with_schema,
):
    store = BackgroundTaskStore(
        db_path=str(runtime_paths_with_schema.background_tasks_db_path)
    )
    task = await _persist_terminal_task(store)
    submitted = []

    class _Service:
        async def submit(
            self,
            intent,
            *,
            prepared_body=None,
            persist_composed_body=None,
        ):
            assert prepared_body is None
            assert persist_composed_body is not None
            await persist_composed_body("recovered body")
            submitted.append(intent.correlation_id)

    producer = build_background_completion_producer(
        _Service(),
        completion_store=store,
    )

    assert await producer.drain_pending() == 1
    assert submitted == [f"{task.task_id}:attempt:0"]
    assert await store.count_pending_completion_intents() == 0


@pytest.mark.asyncio
async def test_pending_completion_drain_caps_each_pass_at_500():
    tasks = [
        SimpleNamespace(task_id=f"task-{index}", attempt_index=0)
        for index in range(600)
    ]

    class _Store:
        def __init__(self):
            self.requested_limit = None

        async def list_pending_completions(self, *, limit):
            self.requested_limit = limit
            return [SimpleNamespace(task=task) for task in tasks[:limit]]

    store = _Store()
    producer = build_background_completion_producer(
        object(),
        completion_store=store,
    )
    handled = []

    async def _record(task):
        handled.append(task.task_id)

    producer._submit_and_acknowledge = _record

    assert await producer.drain_pending(max_items=10_000) == 500
    assert store.requested_limit == 500
    assert len(handled) == 500


@pytest.mark.asyncio
async def test_crash_interrupted_claim_reuses_prepared_body_after_restart(
    runtime_paths_with_schema,
):
    store = BackgroundTaskStore(
        db_path=str(runtime_paths_with_schema.background_tasks_db_path)
    )
    task = await _persist_terminal_task(store)
    claim_token = "claim-before-crash"
    claimed = await store.claim_completion(
        task_id=task.task_id,
        attempt_index=0,
        claim_token=claim_token,
    )
    assert claimed is not None
    intent = task_to_intent(task)
    assert intent is not None

    intent_json = canonical_intent_json(intent)
    await store.save_completion_intent(
        task_id=task.task_id,
        attempt_index=0,
        claim_token=claim_token,
        intent_json=intent_json,
    )
    await store.save_completion_body(
        task_id=task.task_id,
        attempt_index=0,
        claim_token=claim_token,
        intent_json=intent_json,
        composed_body="body saved before crash",
    )

    assert await store.recover_interrupted_completion_claims() == 1
    submitted = []

    class _Service:
        async def submit(
            self,
            intent,
            *,
            prepared_body=None,
            persist_composed_body=None,
        ):
            assert prepared_body == "body saved before crash"
            submitted.append(intent.correlation_id)

    producer = build_background_completion_producer(
        _Service(),
        completion_store=store,
    )
    assert await producer.drain_pending() == 1
    assert submitted == [f"{task.task_id}:attempt:0"]


@pytest.mark.asyncio
async def test_delete_scope_discards_terminal_completion_without_touching_sibling(
    runtime_paths_with_schema,
):
    store = BackgroundTaskStore(
        db_path=str(runtime_paths_with_schema.background_tasks_db_path)
    )
    deleted = await _persist_terminal_task(store, origin_turn_id="deleted-turn")
    sibling = await _persist_terminal_task(store, origin_turn_id="sibling-turn")

    async def run_fn(_task, _token):
        return BackgroundTaskRunResult()

    manager = BackgroundTaskManager(store=store, run_fn=run_fn)
    await manager.start()
    try:
        assert (
            await manager.cancel_scope_and_wait(
                user_id="u1",
                session_id="s1",
                origin_turn_ids={"deleted-turn"},
            )
            == 0
        )
    finally:
        await manager.stop()

    submitted = []

    class _Service:
        async def submit(
            self,
            intent,
            *,
            prepared_body=None,
            persist_composed_body=None,
        ):
            if prepared_body is None:
                assert persist_composed_body is not None
                await persist_composed_body("sibling completion")
            submitted.append(intent.correlation_id)

    producer = build_background_completion_producer(
        _Service(),
        completion_store=store,
    )
    assert await producer.drain_pending() == 1
    assert submitted == [f"{sibling.task_id}:attempt:0"]
    with sqlite3.connect(store.db_path) as connection:
        deleted_row = connection.execute(
            """
            SELECT state, task_json, intent_json, composed_body
            FROM background_task_completion_intents
            WHERE task_id = ? AND attempt_index = 0
            """,
            (deleted.task_id,),
        ).fetchone()
    assert deleted_row == ("discarded", "{}", None, None)


@pytest.mark.asyncio
async def test_delete_waits_for_in_progress_completion_then_discards_failure(
    runtime_paths_with_schema,
):
    store = BackgroundTaskStore(
        db_path=str(runtime_paths_with_schema.background_tasks_db_path)
    )
    task = await _persist_terminal_task(store, origin_turn_id="deleted-turn")
    delivery_started = asyncio.Event()
    release_delivery = asyncio.Event()

    class _FailingService:
        async def submit(
            self,
            intent,
            *,
            prepared_body=None,
            persist_composed_body=None,
        ):
            if prepared_body is None:
                assert persist_composed_body is not None
                await persist_composed_body("prepared before deletion")
            delivery_started.set()
            await release_delivery.wait()
            raise RuntimeError("desktop unavailable")

    producer = build_background_completion_producer(
        _FailingService(),
        completion_store=store,
    )
    delivery = asyncio.create_task(producer(task))
    await delivery_started.wait()

    async def run_fn(_task, _token):
        return BackgroundTaskRunResult()

    manager = BackgroundTaskManager(store=store, run_fn=run_fn)
    await manager.start()
    try:
        deletion = asyncio.create_task(
            manager.cancel_scope_and_wait(
                user_id="u1",
                session_id="s1",
                origin_turn_ids={"deleted-turn"},
            )
        )
        await asyncio.sleep(0.02)
        assert not deletion.done()

        release_delivery.set()
        with pytest.raises(RuntimeError, match="desktop unavailable"):
            await delivery
        assert await deletion == 0
    finally:
        release_delivery.set()
        await manager.stop()

    recovered_submissions = []

    class _RecoveryService:
        async def submit(self, intent, **_kwargs):
            recovered_submissions.append(intent.correlation_id)

    recovery = build_background_completion_producer(
        _RecoveryService(),
        completion_store=store,
    )
    assert await recovery.drain_pending() == 0
    assert recovered_submissions == []
