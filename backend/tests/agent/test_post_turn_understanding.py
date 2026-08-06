from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import time

import pytest

from _shared.memory_schema import apply_memory_shared_schema
from magi.agent.post_turn_understanding import (
    AcceptedBackgroundAttempt,
    AcceptedBackgroundCompletion,
    AcceptedConversationOutcome,
    PostTurnUnderstandingService,
)
from magi.core.sqlite import sqlite_connection_async
from magi.memory.l0.attention import (
    AttentionActionType,
    AttentionKind,
    AttentionUpdateAction,
)
from magi.memory.unified_store import MemoryStoreTuning, UnifiedMemoryStore
from magi.personality.interaction_analyzer import DEFAULT_ANALYSIS
from magi.personality.interaction_batch_analyzer import BatchInteractionAnalysis


class _AttentionStore:
    def __init__(self) -> None:
        self.revision = 0
        self.items: list[dict[str, object]] = []
        self.apply_calls: list[dict[str, object]] = []
        self.checkpoints: list[str] = []

    async def get_attention_snapshot(self, session_id: str) -> dict[str, object]:
        return {
            "session_id": session_id,
            "revision": self.revision,
            "forget_cutoff_at": 0.0,
            "items": deepcopy(self.items),
        }

    async def apply_attention_actions(self, **kwargs):  # type: ignore[no-untyped-def]
        call = dict(kwargs)
        actions = tuple(call["actions"])
        call["actions"] = actions
        self.apply_calls.append(call)
        if int(call["expected_revision"]) != self.revision:
            return None
        for action in actions:
            if action.action is AttentionActionType.ADD:
                self.items.append(
                    {
                        "item_id": f"attention-{len(self.items) + 1}",
                        "kind": action.kind.value if action.kind else None,
                        "summary": action.summary,
                        "status": "active",
                        "source_turn_ids": list(action.source_turn_ids),
                        "source_event_ids": list(action.source_event_ids),
                        "task_id": action.task_id,
                        **(
                            {"task_attempt": action.task_attempt}
                            if action.task_attempt is not None
                            else {}
                        ),
                    }
                )
                continue
            for item in self.items:
                if item["item_id"] != action.target_item_id:
                    continue
                if action.action is AttentionActionType.RESOLVE:
                    item["status"] = "resolved"
                elif action.action is AttentionActionType.BACKGROUND:
                    item["status"] = "background"
                if action.task_attempt is not None:
                    item["task_attempt"] = action.task_attempt
        self.revision += 1
        return {
            "revision": self.revision,
            "items": deepcopy(self.items),
        }

    async def checkpoint_session(self, session_id: str) -> None:
        self.checkpoints.append(session_id)


class _UnifiedMemory:
    def __init__(
        self,
        l0: _AttentionStore | None,
        *,
        memory_db_path: str = "",
        attention_turn_threshold: int = 1,
    ) -> None:
        self.l0 = l0
        self.memory_db_path = memory_db_path
        self.epoch = 0
        self._memory_config_getter = lambda: SimpleNamespace(
            l0=SimpleNamespace(
                attention_update_turn_threshold=attention_turn_threshold,
                attention_update_idle_seconds=30,
                attention_update_max_delay_seconds=90,
            )
        )

    def memory_operation_epoch(self) -> int:
        return self.epoch

    @asynccontextmanager
    async def memory_operation_guard(self):  # type: ignore[no-untyped-def]
        yield


class _PersonalityMemory:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def process_turn_outcome(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(dict(kwargs))
        return True


def _outcome(
    *,
    outcome_id: str,
    source_turn_id: str = "turn-origin",
    task_id: str | None = "task-1",
    task_attempt: int | None = None,
    immediate: bool = True,
    session_id: str = "session-1",
) -> AcceptedConversationOutcome:
    return AcceptedConversationOutcome(
        outcome_id=outcome_id,
        source_turn_id=source_turn_id,
        user_id="local-user",
        session_id=session_id,
        user_message="Please finish this in the background.",
        assistant_response="I will continue and report back.",
        epoch=0,
        accepted_at=time.time(),
        task_id=task_id,
        task_attempt=task_attempt,
        immediate=immediate,
    )


def _completion(
    *,
    outcome_id: str = "completion-message-1",
    status: str = "succeeded",
    task_attempt: int = 0,
) -> AcceptedBackgroundCompletion:
    return AcceptedBackgroundCompletion(
        outcome_id=outcome_id,
        source_turn_id="turn-origin",
        user_id="local-user",
        session_id="session-1",
        task_id="task-1",
        task_status=status,
        response_text="The background work is done.",
        accepted_at=time.time(),
        task_attempt=task_attempt,
    )


async def _wait_idle(service: PostTurnUnderstandingService) -> None:
    scheduler = service.scheduler
    assert scheduler is not None
    assert await scheduler.wait_idle(timeout_seconds=1.0) is True


async def _create_source_tombstone_table(database_path: str) -> None:
    async with sqlite_connection_async(database_path) as db:
        await db.execute(
            """
            CREATE TABLE memory_source_event_tombstones (
                event_id TEXT PRIMARY KEY,
                reason TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        await db.commit()


async def _real_l0_memory(
    *,
    tmp_path: Path,
    attention_turn_threshold: int,
) -> UnifiedMemoryStore:
    memory_db_path = tmp_path / "memory.db"
    await apply_memory_shared_schema(str(memory_db_path))
    memory = UnifiedMemoryStore(
        persist_dir=str(tmp_path / "memory"),
        l1_db_path=str(tmp_path / "l1.db"),
        memory_db_path=str(memory_db_path),
        enable_l0=True,
        enable_l1=False,
        enable_l2=False,
        enable_l3=False,
        enable_l4=False,
        memory_config_getter=lambda: SimpleNamespace(
            l0=SimpleNamespace(
                attention_update_turn_threshold=attention_turn_threshold,
                attention_update_idle_seconds=30,
                attention_update_max_delay_seconds=90,
            )
        ),
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
    return memory


async def _tombstone_turn(database_path: str, turn_id: str) -> None:
    async with sqlite_connection_async(database_path) as db:
        await db.execute(
            """
            INSERT INTO memory_source_event_tombstones(
                event_id, reason, created_at
            ) VALUES (?, 'test_forget', ?)
            """,
            (turn_id, time.time()),
        )
        await db.commit()


def _install_open_loop_analyzer(monkeypatch: pytest.MonkeyPatch) -> None:
    import magi.agent.post_turn_understanding as module

    async def analyze(batch, **_kwargs):  # type: ignore[no-untyped-def]
        return BatchInteractionAnalysis(
            turn_analyses={
                turn.turn_id: DEFAULT_ANALYSIS
                for turn in batch
            },
            attention_actions=(
                AttentionUpdateAction(
                    action=AttentionActionType.ADD,
                    kind=AttentionKind.OPEN_LOOP,
                    summary="Waiting for background work",
                    source_turn_ids=(batch[-1].turn_id,),
                    source_event_ids=("invented-event-id",),
                    task_id="invented-task-id",
                ),
            ),
        )

    monkeypatch.setattr(module, "analyze_interaction_batch", analyze)
    monkeypatch.setattr(
        module,
        "get_personality_feature_flags",
        lambda: SimpleNamespace(
            state_memory_enabled=True,
            state_transition_enabled=False,
            deep_persona_enabled=False,
        ),
    )


@pytest.mark.asyncio
async def test_unique_outcome_identity_allows_same_source_turn_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import magi.agent.post_turn_understanding as module

    analyzed_outcome_ids: list[str] = []

    async def analyze(batch, **_kwargs):  # type: ignore[no-untyped-def]
        analyzed_outcome_ids.extend(turn.turn_id for turn in batch)
        return BatchInteractionAnalysis(
            turn_analyses={
                turn.turn_id: DEFAULT_ANALYSIS
                for turn in batch
            },
            attention_actions=(),
        )

    monkeypatch.setattr(module, "analyze_interaction_batch", analyze)
    monkeypatch.setattr(
        module,
        "get_personality_feature_flags",
        lambda: SimpleNamespace(
            state_memory_enabled=False,
            state_transition_enabled=False,
            deep_persona_enabled=False,
        ),
    )
    l0 = _AttentionStore()
    service = PostTurnUnderstandingService(
        unified_memory=_UnifiedMemory(l0),
        self_memory=None,
    )
    first = _outcome(outcome_id="accepted-ack", task_id=None)
    second = _outcome(outcome_id="accepted-final", task_id=None)

    try:
        assert await service.admit(first) is True
        await _wait_idle(service)
        assert await service.admit(second) is True
        await _wait_idle(service)
        assert await service.admit(first) is False

        assert analyzed_outcome_ids == ["accepted-ack", "accepted-final"]
        assert [
            call["last_processed_turn_id"]
            for call in l0.apply_calls
        ] == ["turn-origin", "turn-origin"]
    finally:
        await service.shutdown(flush=False)


@pytest.mark.asyncio
async def test_completion_before_ack_blocks_stale_open_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_open_loop_analyzer(monkeypatch)
    l0 = _AttentionStore()
    personality = _PersonalityMemory()
    service = PostTurnUnderstandingService(
        unified_memory=_UnifiedMemory(l0),
        self_memory=personality,
    )
    completion = _completion()

    try:
        assert await service.admit_background_completion(completion) is True
        assert await service.admit_background_completion(completion) is False
        assert await service.admit(_outcome(outcome_id="accepted-ack")) is True
        await _wait_idle(service)

        assert l0.items == []
        assert l0.checkpoints == ["session-1"]
        assert len(personality.calls) == 1
        assert all(
            action.source_event_ids == ()
            for call in l0.apply_calls
            for action in call["actions"]
        )
    finally:
        await service.shutdown(flush=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["succeeded", "failed", "cancelled"])
async def test_terminal_completion_closes_existing_task_attention(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    _install_open_loop_analyzer(monkeypatch)
    l0 = _AttentionStore()
    personality = _PersonalityMemory()
    service = PostTurnUnderstandingService(
        unified_memory=_UnifiedMemory(l0),
        self_memory=personality,
    )

    try:
        assert await service.admit(_outcome(outcome_id="accepted-ack")) is True
        await _wait_idle(service)
        assert l0.items == [
            {
                "item_id": "attention-1",
                "kind": "open_loop",
                "summary": "Waiting for background work",
                "status": "active",
                "source_turn_ids": ["turn-origin"],
                "source_event_ids": [],
                "task_id": "task-1",
                "task_attempt": 0,
            }
        ]

        assert await service.admit_background_completion(
            _completion(status=status)
        ) is True

        assert l0.items[0]["status"] == "resolved"
        assert l0.checkpoints == ["session-1"]
        assert len(personality.calls) == 1
        direct_call = l0.apply_calls[-1]
        assert direct_call["source_turn_accepted_at"] == {}
        assert all(
            action.source_turn_ids == ()
            and action.source_event_ids == ()
            for action in direct_call["actions"]
        )
    finally:
        await service.shutdown(flush=False)


@pytest.mark.asyncio
async def test_completion_only_closes_task_open_loop_from_mixed_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import magi.agent.post_turn_understanding as module

    async def analyze(batch, **_kwargs):  # type: ignore[no-untyped-def]
        return BatchInteractionAnalysis(
            turn_analyses={
                batch[0].turn_id: DEFAULT_ANALYSIS,
            },
            attention_actions=(
                AttentionUpdateAction(
                    action=AttentionActionType.ADD,
                    kind=AttentionKind.OPEN_LOOP,
                    summary="Waiting for the background task",
                    source_turn_ids=(batch[0].turn_id,),
                ),
                AttentionUpdateAction(
                    action=AttentionActionType.ADD,
                    kind=AttentionKind.FOCUS,
                    summary="The user is comparing memory designs",
                    source_turn_ids=(batch[0].turn_id,),
                ),
            ),
        )

    monkeypatch.setattr(module, "analyze_interaction_batch", analyze)
    l0 = _AttentionStore()
    service = PostTurnUnderstandingService(
        unified_memory=_UnifiedMemory(l0),
        self_memory=None,
    )
    try:
        assert await service.admit(
            _outcome(
                outcome_id="accepted-mixed-attention",
                task_attempt=0,
            )
        )
        await _wait_idle(service)
        by_kind = {str(item["kind"]): item for item in l0.items}
        assert by_kind["open_loop"]["task_id"] == "task-1"
        assert by_kind["focus"]["task_id"] is None

        assert await service.admit_background_completion(_completion())
        assert by_kind["open_loop"]["status"] == "resolved"
        assert by_kind["focus"]["status"] == "active"
    finally:
        await service.shutdown(flush=False)


@pytest.mark.asyncio
async def test_fresh_runtime_can_compensate_existing_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_open_loop_analyzer(monkeypatch)
    l0 = _AttentionStore()
    first_runtime = PostTurnUnderstandingService(
        unified_memory=_UnifiedMemory(l0),
        self_memory=None,
    )
    assert await first_runtime.admit(_outcome(outcome_id="accepted-ack")) is True
    await _wait_idle(first_runtime)
    await first_runtime.shutdown(flush=False)
    assert l0.items[0]["status"] == "active"

    restarted_runtime = PostTurnUnderstandingService(
        unified_memory=_UnifiedMemory(l0),
        self_memory=None,
    )
    try:
        assert await restarted_runtime.admit_background_completion(
            _completion()
        ) is True
        assert l0.items[0]["status"] == "resolved"
        assert l0.checkpoints == ["session-1"]
    finally:
        await restarted_runtime.shutdown(flush=False)


@pytest.mark.asyncio
async def test_forgotten_turn_blocks_personality_when_l0_is_disabled(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import magi.agent.post_turn_understanding as module

    database_path = str(tmp_path / "memory.db")
    await _create_source_tombstone_table(database_path)
    await _tombstone_turn(database_path, "turn-origin")
    analysis_calls = 0

    async def unexpected_analysis(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        nonlocal analysis_calls
        analysis_calls += 1
        raise AssertionError("forgotten source must not be analyzed")

    monkeypatch.setattr(module, "analyze_interaction_batch", unexpected_analysis)
    monkeypatch.setattr(
        module,
        "get_personality_feature_flags",
        lambda: SimpleNamespace(
            state_memory_enabled=True,
            state_transition_enabled=False,
            deep_persona_enabled=False,
        ),
    )
    personality = _PersonalityMemory()
    service = PostTurnUnderstandingService(
        unified_memory=_UnifiedMemory(None, memory_db_path=database_path),
        self_memory=personality,
    )

    try:
        assert await service.admit(_outcome(outcome_id="accepted-forgotten")) is True
        await _wait_idle(service)
        assert analysis_calls == 0
        assert personality.calls == []
    finally:
        await service.shutdown(flush=False)


@pytest.mark.asyncio
async def test_forget_request_after_commit_blocks_delayed_enqueue_with_l0_disabled(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import magi.agent.post_turn_understanding as module

    database_path = str(tmp_path / "memory.db")
    committed_at = time.time() - 10
    forget_created_at = committed_at + 5
    async with sqlite_connection_async(database_path) as db:
        await db.execute(
            """
            CREATE TABLE memory_forget_operations (
                operation_id TEXT PRIMARY KEY,
                execution_ready INTEGER NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        await db.execute(
            """
            INSERT INTO memory_forget_operations(
                operation_id, execution_ready, created_at
            ) VALUES ('forget-after-commit', 1, ?)
            """,
            (forget_created_at,),
        )
        await db.commit()

    analysis_calls = 0

    async def unexpected_analysis(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        nonlocal analysis_calls
        analysis_calls += 1
        raise AssertionError("pre-forget durable outcome must not be analyzed")

    monkeypatch.setattr(module, "analyze_interaction_batch", unexpected_analysis)
    monkeypatch.setattr(
        module,
        "get_personality_feature_flags",
        lambda: SimpleNamespace(
            state_memory_enabled=True,
            state_transition_enabled=False,
            deep_persona_enabled=False,
        ),
    )
    personality = _PersonalityMemory()
    service = PostTurnUnderstandingService(
        unified_memory=_UnifiedMemory(None, memory_db_path=database_path),
        self_memory=personality,
    )
    delayed = replace(
        _outcome(
            outcome_id="accepted-before-forget-enqueued-late",
            task_id=None,
        ),
        accepted_at=committed_at,
    )
    try:
        assert await service.admit(delayed) is True
        await _wait_idle(service)
        assert analysis_calls == 0
        assert personality.calls == []
    finally:
        await service.shutdown(flush=False)


@pytest.mark.asyncio
async def test_unactivated_chat_forget_intent_does_not_block_post_turn_work(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import magi.agent.post_turn_understanding as module

    database_path = str(tmp_path / "memory.db")
    created_at = time.time()
    async with sqlite_connection_async(database_path) as db:
        await db.execute(
            """
            CREATE TABLE memory_forget_operations (
                operation_id TEXT PRIMARY KEY,
                execution_ready INTEGER NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        await db.execute(
            """
            INSERT INTO memory_forget_operations(
                operation_id, execution_ready, created_at
            ) VALUES ('prepared-chat-forget', 0, ?)
            """,
            (created_at,),
        )
        await db.commit()

    analyzed: list[str] = []

    async def analyze(batch, **_kwargs):  # type: ignore[no-untyped-def]
        analyzed.extend(turn.turn_id for turn in batch)
        return BatchInteractionAnalysis(
            turn_analyses={
                turn.turn_id: DEFAULT_ANALYSIS
                for turn in batch
            },
            attention_actions=(),
        )

    monkeypatch.setattr(module, "analyze_interaction_batch", analyze)
    service = PostTurnUnderstandingService(
        unified_memory=_UnifiedMemory(
            _AttentionStore(),
            memory_db_path=database_path,
        ),
        self_memory=None,
    )
    try:
        assert await service.admit(
            replace(
                _outcome(
                    outcome_id="accepted-before-activation",
                    source_turn_id="turn-before-activation",
                    task_id=None,
                ),
                accepted_at=created_at - 1,
            )
        )
        await _wait_idle(service)
        assert analyzed == ["accepted-before-activation"]

        async with sqlite_connection_async(database_path) as db:
            await db.execute(
                """
                UPDATE memory_forget_operations
                SET execution_ready = 1
                WHERE operation_id = 'prepared-chat-forget'
                """
            )
            await db.commit()
        assert await service.admit(
            replace(
                _outcome(
                    outcome_id="accepted-after-activation",
                    source_turn_id="turn-after-activation",
                    task_id=None,
                ),
                accepted_at=created_at - 1,
            )
        )
        await _wait_idle(service)
        assert analyzed == ["accepted-before-activation"]
    finally:
        await service.shutdown(flush=False)


@pytest.mark.asyncio
async def test_forget_during_analysis_blocks_every_projection(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import magi.agent.post_turn_understanding as module

    database_path = str(tmp_path / "memory.db")
    await _create_source_tombstone_table(database_path)
    l0 = _AttentionStore()
    personality = _PersonalityMemory()

    async def analyze(batch, **_kwargs):  # type: ignore[no-untyped-def]
        await _tombstone_turn(database_path, "turn-origin")
        return BatchInteractionAnalysis(
            turn_analyses={
                batch[0].turn_id: DEFAULT_ANALYSIS,
            },
            attention_actions=(
                AttentionUpdateAction(
                    action=AttentionActionType.ADD,
                    kind=AttentionKind.FOCUS,
                    summary="This must be discarded",
                    source_turn_ids=(batch[0].turn_id,),
                ),
            ),
        )

    monkeypatch.setattr(module, "analyze_interaction_batch", analyze)
    monkeypatch.setattr(
        module,
        "get_personality_feature_flags",
        lambda: SimpleNamespace(
            state_memory_enabled=True,
            state_transition_enabled=False,
            deep_persona_enabled=False,
        ),
    )
    service = PostTurnUnderstandingService(
        unified_memory=_UnifiedMemory(
            l0,
            memory_db_path=database_path,
        ),
        self_memory=personality,
    )

    try:
        assert await service.admit(_outcome(outcome_id="accepted-racing")) is True
        await _wait_idle(service)
        assert l0.apply_calls == []
        assert personality.calls == []
    finally:
        await service.shutdown(flush=False)


@pytest.mark.asyncio
async def test_delayed_ack_binds_to_running_retry_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import magi.agent.post_turn_understanding as module

    analysis_started = asyncio.Event()
    allow_analysis = asyncio.Event()

    async def analyze(batch, **_kwargs):  # type: ignore[no-untyped-def]
        analysis_started.set()
        await allow_analysis.wait()
        return BatchInteractionAnalysis(
            turn_analyses={
                turn.turn_id: DEFAULT_ANALYSIS
                for turn in batch
            },
            attention_actions=(
                AttentionUpdateAction(
                    action=AttentionActionType.ADD,
                    kind=AttentionKind.OPEN_LOOP,
                    summary="Retry is still running",
                    source_turn_ids=(batch[0].turn_id,),
                ),
            ),
        )

    monkeypatch.setattr(module, "analyze_interaction_batch", analyze)
    l0 = _AttentionStore()
    service = PostTurnUnderstandingService(
        unified_memory=_UnifiedMemory(l0),
        self_memory=None,
    )
    try:
        assert await service.admit(
            _outcome(
                outcome_id="accepted-ack-attempt-0",
                task_attempt=0,
            )
        )
        await analysis_started.wait()
        assert await service.admit_background_completion(
            _completion(
                outcome_id="completion-attempt-0",
                status="failed",
                task_attempt=0,
            )
        )
        assert await service.admit_background_attempt(
            AcceptedBackgroundAttempt(
                outcome_id="attempt-1-started",
                source_turn_id="turn-origin",
                user_id="local-user",
                session_id="session-1",
                task_id="task-1",
                task_attempt=1,
                accepted_at=time.time(),
            )
        )
        allow_analysis.set()
        await _wait_idle(service)

        assert len(l0.items) == 1
        assert l0.items[0]["task_attempt"] == 1
        assert l0.items[0]["status"] == "active"
        assert await service.admit_background_completion(
            _completion(
                outcome_id="completion-attempt-1",
                task_attempt=1,
            )
        )
        assert l0.items[0]["status"] == "resolved"
    finally:
        allow_analysis.set()
        await service.shutdown(flush=False)


@pytest.mark.asyncio
async def test_newer_completion_closes_older_task_attempt_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_open_loop_analyzer(monkeypatch)
    l0 = _AttentionStore()
    service = PostTurnUnderstandingService(
        unified_memory=_UnifiedMemory(l0),
        self_memory=None,
    )
    try:
        assert await service.admit(
            _outcome(
                outcome_id="accepted-attempt-0",
                task_attempt=0,
            )
        )
        await _wait_idle(service)
        assert l0.items[0]["task_attempt"] == 0

        assert await service.admit_background_completion(
            _completion(
                outcome_id="completion-attempt-1",
                task_attempt=1,
            )
        )
        assert l0.items[0]["status"] == "resolved"
    finally:
        await service.shutdown(flush=False)


@pytest.mark.asyncio
async def test_terminal_completion_blocks_delayed_attempt_reopen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_open_loop_analyzer(monkeypatch)
    l0 = _AttentionStore()
    service = PostTurnUnderstandingService(
        unified_memory=_UnifiedMemory(l0),
        self_memory=None,
    )
    delayed_attempt_entered = asyncio.Event()
    release_delayed_attempt = asyncio.Event()
    original_reopen = service._reopen_task_attention

    async def delayed_reopen(attempt, *, expected_epoch):  # type: ignore[no-untyped-def]
        delayed_attempt_entered.set()
        await release_delayed_attempt.wait()
        await original_reopen(attempt, expected_epoch=expected_epoch)

    monkeypatch.setattr(service, "_reopen_task_attention", delayed_reopen)
    try:
        assert await service.admit(
            _outcome(
                outcome_id="accepted-attempt-0",
                task_attempt=0,
            )
        )
        await _wait_idle(service)
        assert await service.admit_background_completion(
            _completion(
                outcome_id="completion-attempt-0",
                task_attempt=0,
            )
        )
        assert l0.items[0]["status"] == "resolved"
        assert l0.items[0]["task_attempt"] == 0

        delayed_attempt = asyncio.create_task(
            service.admit_background_attempt(
                AcceptedBackgroundAttempt(
                    outcome_id="attempt-1-started",
                    source_turn_id="turn-origin",
                    user_id="local-user",
                    session_id="session-1",
                    task_id="task-1",
                    task_attempt=1,
                    accepted_at=time.time(),
                )
            )
        )
        await delayed_attempt_entered.wait()
        assert await service.admit_background_completion(
            _completion(
                outcome_id="completion-attempt-1",
                task_attempt=1,
            )
        )

        release_delayed_attempt.set()
        assert await delayed_attempt is True
        assert l0.items[0]["status"] == "resolved"
        assert l0.items[0]["task_attempt"] == 0
    finally:
        release_delayed_attempt.set()
        await service.shutdown(flush=False)


@pytest.mark.asyncio
async def test_partial_revoke_reanalyzes_only_surviving_outcomes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import magi.agent.post_turn_understanding as module

    first_analysis_started = asyncio.Event()
    allow_first_analysis = asyncio.Event()
    analyzed_batches: list[list[str]] = []

    async def analyze(batch, **_kwargs):  # type: ignore[no-untyped-def]
        analyzed_batches.append([turn.turn_id for turn in batch])
        if len(analyzed_batches) == 1:
            first_analysis_started.set()
            await allow_first_analysis.wait()
        return BatchInteractionAnalysis(
            turn_analyses={
                turn.turn_id: DEFAULT_ANALYSIS
                for turn in batch
            },
            attention_actions=(),
        )

    monkeypatch.setattr(module, "analyze_interaction_batch", analyze)
    monkeypatch.setattr(
        module,
        "get_personality_feature_flags",
        lambda: SimpleNamespace(
            state_memory_enabled=True,
            state_transition_enabled=False,
            deep_persona_enabled=False,
        ),
    )
    personality = _PersonalityMemory()
    service = PostTurnUnderstandingService(
        unified_memory=_UnifiedMemory(
            _AttentionStore(),
            attention_turn_threshold=3,
        ),
        self_memory=personality,
    )
    assert service.scheduler is not None
    service.scheduler._retry_initial_seconds = 0.0
    service.scheduler._retry_max_seconds = 0.0
    outcomes = [
        replace(
            _outcome(
                outcome_id=f"accepted-{turn_id}",
                source_turn_id=turn_id,
                task_id=None,
                immediate=False,
            ),
            user_message=turn_id,
        )
        for turn_id in ("turn-a", "turn-b", "turn-c")
    ]
    try:
        for outcome in outcomes:
            assert await service.admit(outcome)
        await first_analysis_started.wait()
        assert await service.revoke_source_turns(
            session_id="session-1",
            source_turn_ids=["turn-b"],
        ) == 1
        allow_first_analysis.set()
        await _wait_idle(service)

        assert analyzed_batches == [
            ["accepted-turn-a", "accepted-turn-b", "accepted-turn-c"],
            ["accepted-turn-a", "accepted-turn-c"],
        ]
        assert [call["user_message"] for call in personality.calls] == [
            "turn-a",
            "turn-c",
        ]
    finally:
        allow_first_analysis.set()
        await service.shutdown(flush=False)


@pytest.mark.asyncio
async def test_analysis_concurrency_is_globally_bounded_and_locks_reclaim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import magi.agent.post_turn_understanding as module

    active = 0
    maximum_active = 0
    two_started = asyncio.Event()
    release = asyncio.Event()

    async def analyze(batch, **_kwargs):  # type: ignore[no-untyped-def]
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        if active == 2:
            two_started.set()
        await release.wait()
        active -= 1
        return BatchInteractionAnalysis(
            turn_analyses={
                turn.turn_id: DEFAULT_ANALYSIS
                for turn in batch
            },
            attention_actions=(),
        )

    monkeypatch.setattr(module, "analyze_interaction_batch", analyze)
    monkeypatch.setattr(
        module,
        "get_personality_feature_flags",
        lambda: SimpleNamespace(
            state_memory_enabled=True,
            state_transition_enabled=False,
            deep_persona_enabled=False,
        ),
    )
    service = PostTurnUnderstandingService(
        unified_memory=_UnifiedMemory(None),
        self_memory=_PersonalityMemory(),
    )
    try:
        for index in range(4):
            assert await service.admit(
                _outcome(
                    outcome_id=f"accepted-{index}",
                    source_turn_id=f"turn-{index}",
                    task_id=None,
                    session_id=f"session-{index}",
                )
            )
        await asyncio.wait_for(two_started.wait(), timeout=1.0)
        await asyncio.sleep(0)
        assert maximum_active == 2
        release.set()
        await _wait_idle(service)
        assert service._session_locks == {}
        assert service._session_lock_users == {}
    finally:
        release.set()
        await service.shutdown(flush=False)


@pytest.mark.asyncio
async def test_cancelled_session_lock_waiter_is_reclaimed() -> None:
    service = PostTurnUnderstandingService(
        unified_memory=_UnifiedMemory(_AttentionStore()),
        self_memory=None,
    )

    async def wait_for_same_session() -> None:
        async with service._session_guard("session-cancelled-waiter"):
            return

    try:
        async with service._session_guard("session-cancelled-waiter"):
            waiter = asyncio.create_task(wait_for_same_session())
            while (
                service._session_lock_users.get(
                    "session-cancelled-waiter",
                    0,
                )
                < 2
            ):
                await asyncio.sleep(0)
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            assert service._session_lock_users == {
                "session-cancelled-waiter": 1,
            }
        assert service._session_locks == {}
        assert service._session_lock_users == {}
    finally:
        await service.shutdown(flush=False)


@pytest.mark.asyncio
async def test_l0_revision_conflict_retries_before_personality_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import magi.agent.post_turn_understanding as module

    analysis_started = asyncio.Event()
    allow_analysis = asyncio.Event()
    analysis_calls = 0

    async def analyze(batch, **_kwargs):  # type: ignore[no-untyped-def]
        nonlocal analysis_calls
        analysis_calls += 1
        if analysis_calls == 1:
            analysis_started.set()
            await allow_analysis.wait()
        return BatchInteractionAnalysis(
            turn_analyses={
                turn.turn_id: DEFAULT_ANALYSIS
                for turn in batch
            },
            attention_actions=(),
        )

    monkeypatch.setattr(module, "analyze_interaction_batch", analyze)
    monkeypatch.setattr(
        module,
        "get_personality_feature_flags",
        lambda: SimpleNamespace(
            state_memory_enabled=True,
            state_transition_enabled=False,
            deep_persona_enabled=False,
        ),
    )
    l0 = _AttentionStore()
    l0.items.append(
        {
            "item_id": "attention-task",
            "kind": "open_loop",
            "summary": "Existing task",
            "status": "active",
            "source_turn_ids": ["turn-task"],
            "source_event_ids": [],
            "task_id": "other-task",
            "task_attempt": 0,
        }
    )
    personality = _PersonalityMemory()
    service = PostTurnUnderstandingService(
        unified_memory=_UnifiedMemory(l0),
        self_memory=personality,
    )
    assert service.scheduler is not None
    service.scheduler._retry_initial_seconds = 0.0
    service.scheduler._retry_max_seconds = 0.0
    try:
        assert await service.admit(
            _outcome(
                outcome_id="accepted-racing-revision",
                task_id=None,
            )
        )
        await analysis_started.wait()
        assert await service.admit_background_completion(
            AcceptedBackgroundCompletion(
                outcome_id="other-task-completion",
                source_turn_id="turn-task",
                user_id="local-user",
                session_id="session-1",
                task_id="other-task",
                task_status="succeeded",
                response_text="done",
                accepted_at=time.time(),
                task_attempt=0,
            )
        )
        allow_analysis.set()
        await _wait_idle(service)

        assert analysis_calls == 2
        assert len(personality.calls) == 1
    finally:
        allow_analysis.set()
        await service.shutdown(flush=False)


@pytest.mark.asyncio
async def test_clear_all_memory_drops_queued_old_epoch_before_analysis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import magi.agent.post_turn_understanding as module

    analysis_calls = 0

    async def analyze(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        nonlocal analysis_calls
        analysis_calls += 1
        return None

    monkeypatch.setattr(module, "analyze_interaction_batch", analyze)
    monkeypatch.setattr(
        module,
        "get_personality_feature_flags",
        lambda: SimpleNamespace(
            state_memory_enabled=False,
            state_transition_enabled=False,
            deep_persona_enabled=False,
        ),
    )
    memory = await _real_l0_memory(
        tmp_path=tmp_path,
        attention_turn_threshold=20,
    )
    assert memory.l0 is not None
    service = PostTurnUnderstandingService(
        unified_memory=memory,
        self_memory=None,
    )
    service_closed = False
    try:
        assert await service.admit(
            _outcome(
                outcome_id="accepted-before-full-clear",
                task_id=None,
                immediate=False,
            )
        )
        assert service.has_pending_work("session-1") is True
        assert memory.memory_operation_epoch() == 0

        await memory.clear_all_memory()
        assert memory.memory_operation_epoch() == 1

        assert await service.shutdown(flush=True, timeout_seconds=2.0) is True
        service_closed = True
        assert analysis_calls == 0
        assert (
            await memory.l0.get_attention_snapshot("session-1")
        )["items"] == []
    finally:
        if not service_closed:
            await service.shutdown(flush=False)
        await memory.shutdown()


@pytest.mark.asyncio
async def test_clear_all_memory_blocks_in_flight_analysis_from_writing_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import magi.agent.post_turn_understanding as module

    analysis_started = asyncio.Event()
    release_analysis = asyncio.Event()
    analysis_calls = 0

    async def analyze(batch, **_kwargs):  # type: ignore[no-untyped-def]
        nonlocal analysis_calls
        analysis_calls += 1
        analysis_started.set()
        await release_analysis.wait()
        return BatchInteractionAnalysis(
            turn_analyses={
                turn.turn_id: DEFAULT_ANALYSIS
                for turn in batch
            },
            attention_actions=(
                AttentionUpdateAction(
                    action=AttentionActionType.ADD,
                    kind=AttentionKind.FOCUS,
                    summary="This stale focus must not return after a full clear",
                    source_turn_ids=(batch[-1].turn_id,),
                ),
            ),
        )

    monkeypatch.setattr(module, "analyze_interaction_batch", analyze)
    monkeypatch.setattr(
        module,
        "get_personality_feature_flags",
        lambda: SimpleNamespace(
            state_memory_enabled=False,
            state_transition_enabled=False,
            deep_persona_enabled=False,
        ),
    )
    memory = await _real_l0_memory(
        tmp_path=tmp_path,
        attention_turn_threshold=1,
    )
    assert memory.l0 is not None
    service = PostTurnUnderstandingService(
        unified_memory=memory,
        self_memory=None,
    )
    try:
        assert await service.admit(
            _outcome(
                outcome_id="accepted-analysis-during-full-clear",
                task_id=None,
                immediate=True,
            )
        )
        await asyncio.wait_for(analysis_started.wait(), timeout=1.0)

        await memory.clear_all_memory()
        assert memory.memory_operation_epoch() == 1

        release_analysis.set()
        await _wait_idle(service)
        assert analysis_calls == 1
        assert (
            await memory.l0.get_attention_snapshot("session-1")
        )["items"] == []
    finally:
        release_analysis.set()
        await service.shutdown(flush=False)
        await memory.shutdown()
