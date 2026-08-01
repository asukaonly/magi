from __future__ import annotations

import time

import pytest

from magi.agent.runtime.contracts import FactRecord
from magi.chat.task_agent.fact_classifier import ChatFactClassifier
from magi.chat.task_agent.session_run_coordinator import SessionRunCoordinator
from magi.agent.task_agents.common import ExecutionResult, ExploreTaskCompletedPayload, IncomingFactKind, UserMessagePayload
from magi.agent.task_agents.explore.constants import EXPLORE_TASK_COMPLETED
from magi.agent.task_agents.explore.contracts import ExploreRuntimeContext
from magi.agent.task_agents.explore.postprocess_service import ExplorePostProcessService
from magi.agent.workers.worker_manager import WORKER_AGENT_COMPLETED, WorkerAgentManager, WorkerRunState


class _RecordingTaskAgentManager:
    def __init__(self) -> None:
        self.calls: list[tuple[object, str, FactRecord]] = []

    async def add_fact_to_agent(self, agent_type, agent_id, fact):  # type: ignore[no-untyped-def]
        self.calls.append((agent_type, agent_id, fact))
        return True


@pytest.mark.asyncio
async def test_worker_manager_tags_result_facts_with_run_metadata() -> None:
    manager = WorkerAgentManager()
    manager._task_agent_manager = _RecordingTaskAgentManager()
    run_state = WorkerRunState(
        worker_id="worker-1",
        subagent_type="CodeExplore",
        description="Inspect backend",
        prompt="Inspect backend",
        orchestration_id="orch-1",
        subtask_id="subtask-1",
        parent_task_agent_type="chat",
        parent_task_agent_id="session-1",
        target_task_agent_type="chat",
        target_task_agent_id="session-1",
        user_id="user-1",
        session_id="session-1",
        turn_id="turn-1",
        run_id="run-1",
        run_revision=3,
        user_message_generation=7,
        created_at=time.time(),
    )

    await manager._publish_worker_fact(
        run_state=run_state,
        event_type=WORKER_AGENT_COMPLETED,
        internal_payload={"worker_result": {"summary": "done"}},
    )

    fact = manager._task_agent_manager.calls[0][2]
    assert fact.payload["run_id"] == "run-1"
    assert fact.payload["run_revision"] == 3
    assert fact.user_message_generation == 7


@pytest.mark.asyncio
async def test_explore_postprocess_tags_upstream_fact_with_run_metadata() -> None:
    manager = _RecordingTaskAgentManager()
    service = ExplorePostProcessService(get_task_agent_manager=lambda: manager)
    payload = ExploreTaskCompletedPayload(
        user_id="user-1",
        session_id="session-1",
        root_user_message="Analyze repo",
        markdown_dossier="report",
        run_id="run-1",
        run_revision=2,
        turn_id="turn-1",
    )
    context = ExploreRuntimeContext(
        latest_fact=FactRecord(
            agent_id="explore:user-1",
            event_type="EXPLORE_TASK_REQUEST",
            payload=payload.to_dict(),
            agent_type="explore",
            agent_instance_id="user-1",
            correlation_id="corr-1",
            user_message_generation=7,
        ),
        recent_facts=[],
        batch_facts=[],
        agent_id="user-1",
        agent_type="explore",
        runtime_key="explore:user-1",
        user_id="user-1",
        session_id="session-1",
        history_key="user-1::session-1",
        history=[],
        latest_user_message="Analyze repo",
        incoming_fact_kind=IncomingFactKind.EXPLORE_TASK_REQUEST,
        upstream_task_agent_type="chat",
        upstream_task_agent_id="session-1",
        latest_payload=payload,
        user_message_generation=7,
    )

    await service.handle(
        context,
        ExecutionResult(
            mode="explore_task_render",  # type: ignore[arg-type]
            response_text="report",
            root_user_message="Analyze repo",
            turn_id="turn-1",
        ),
    )

    fact = manager.calls[0][2]
    assert fact.event_type == EXPLORE_TASK_COMPLETED
    assert fact.payload["run_id"] == "run-1"
    assert fact.payload["run_revision"] == 2
    assert fact.user_message_generation == 7


def test_session_run_coordinator_records_stale_result_and_drops_it_from_planning() -> None:
    classifier = ChatFactClassifier()
    coordinator = SessionRunCoordinator()
    first_turn = coordinator.handle_user_turn(
        UserMessagePayload(
            user_id="user-1",
            session_id="session-1",
            content="Inspect backend",
            turn_id="turn-1",
        )
    )
    coordinator.handle_user_turn(
        UserMessagePayload(
            user_id="user-1",
            session_id="session-1",
            # Strict cancel phrase — InterruptionClassifier requires the full
            # normalized message to match a canonical phrase (see
            # interruption_phrases.yaml). Longer sentences defer instead.
            content="Stop.",
            turn_id="turn-2",
        )
    )

    stale_fact = FactRecord(
        agent_id="chat:session-1",
        event_type=WORKER_AGENT_COMPLETED,
        payload={
            "user_id": "user-1",
            "session_id": "session-1",
            "worker_id": "worker-1",
            "worker_result": {"summary": "old backend result"},
            "run_id": first_turn.active_run.run_id,
            "run_revision": 0,
        },
        agent_type="chat",
        agent_instance_id="session-1",
        correlation_id="worker-1",
    )

    routed = coordinator.route(
        classifier.classify(
            agent_id="session-1",
            latest_fact=stale_fact,
            batch_facts=[stale_fact],
        )
    )
    active_run = coordinator.get_active_run("session-1")

    assert active_run is not None
    assert len(active_run.stale_results) == 1
    assert active_run.stale_results[0].run_id == first_turn.active_run.run_id
    assert routed.planner_fact_kind == IncomingFactKind.OTHER_FACT
