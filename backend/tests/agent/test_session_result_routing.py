from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from magi.agent.execution.function_calling import FunctionCallingOrchestrator, ToolCall
from magi.agent.task_agents.handlers.contracts import ChatRuntimeContext, IntentDecision
from magi.chat.task_agent.planning_service import ChatPlanningService
from magi.chat.task_agent.prompt_service import ChatPromptService
from magi.llm.model_context import unknown_model_context
from magi.agent.task_agents.common import (
    ExecutionMode,
    ExecutionRequest,
    ExecutionResult,
    IncomingFactKind,
    OrchestrationPlan,
    ToolSelection,
    UserMessagePayload,
    WorkerUpdatePayload,
)
from magi.agent.task_agents.explore.contracts import ExploreRuntimeContext
from magi.agent.task_agents.explore.postprocess_service import ExplorePostProcessService
from magi.agent.task_orchestrator import TaskOrchestrator
from magi.agent.runtime.contracts import FactRecord
from magi.agent.workers.worker_manager import WORKER_AGENT_COMPLETED, WorkerAgentManager, WorkerRunState
from magi.tools.builtin.file_read_tool import FileReadTool
from magi.tools.builtin.glob_tool import GlobTool
from magi.tools.builtin.grep_tool import GrepTool
from magi.tools.registry import ToolRegistry
from magi.tools.schema import ToolResult


def _registry_with_file_tools() -> ToolRegistry:
    """Build a registry with the file-tool candidates the planning prompt
    consults. Using ``ToolRegistry()`` directly leaves ToolHintResolver
    with nothing to look up and the prompt drops the # Tool Guidance /
    ## Task Hints sections."""
    registry = ToolRegistry()
    for tool_class in (GlobTool, GrepTool, FileReadTool):
        registry.register(tool_class)
    return registry


async def _fake_plan_subtasks(*args, **kwargs):  # type: ignore[no-untyped-def]
    _ = (args, kwargs)
    raise AssertionError("plan_subtasks should not be called in this test")


async def _fake_aggregate(*args, **kwargs):  # type: ignore[no-untyped-def]
    _ = (args, kwargs)
    raise AssertionError("aggregate_orchestration should not be called in this test")


def _fake_register_user_message(*args, **kwargs) -> None:  # type: ignore[no-untyped-def]
    _ = (args, kwargs)


class _FakePromptService:
    def filter_history_for_aggregation(self, history):  # type: ignore[no-untyped-def]
        return list(history)


class _FakeToolStateView:
    def record(self, history_key: str, record: dict) -> None:
        _ = (history_key, record)


class _FakeContextAssembler:
    # postprocess_service aliases context_assembler.tool_state_view onto
    # its own _tool_state_view; the fake must expose the same attribute.
    tool_state_view = _FakeToolStateView()

    def append_user_message(self, history_key: str, content: str) -> None:
        _ = (history_key, content)


class _RecordingTaskAgentManager:
    def __init__(self) -> None:
        self.calls: list[tuple[object, str, FactRecord]] = []

    async def add_fact_to_agent(self, agent_type, agent_id, fact):  # type: ignore[no-untyped-def]
        self.calls.append((agent_type, agent_id, fact))
        return True


class _DummyLLMAdapter:
    model_name = "test-model"
    provider_name = "openai"


class _RecordingExecuteToolRegistry:
    def __init__(self, result: ToolResult) -> None:
        self.result = result
        self.calls: list[tuple[str, dict, object]] = []

    async def execute(self, name: str, payload: dict, context):  # type: ignore[no-untyped-def]
        self.calls.append((name, payload, context))
        return self.result

    def get_tool_info(self, tool_name: str) -> dict[str, object]:
        # Return a minimal but non-empty descriptor for the file/web tool
        # candidates the planning service consults via ToolHintResolver.
        # Without this the resolver filters every candidate and the
        # generated planning prompt loses its "## Task Hints" section.
        known = {"glob", "grep", "file_read", "file_edit", "file_write", "bash", "web-search", "web-fetch", "agent"}
        if tool_name not in known:
            return {}
        return {
            "name": tool_name,
            "description": tool_name,
            "metadata": {},
            "parameters": [],
        }


@pytest.mark.asyncio
async def test_task_orchestrator_chat_context_targets_session_chat_agent() -> None:
    orchestrator = TaskOrchestrator(
        runtime_key="chat:user-1",
        tool_registry=ToolRegistry(),
        plan_subtasks=_fake_plan_subtasks,
        aggregate_orchestration=_fake_aggregate,
        register_user_message=_fake_register_user_message,
        parent_task_agent_type="chat",
    )

    context = await orchestrator._build_agent_tool_context("user-1", "session-1")

    assert context.env_vars["target_task_agent_type"] == "chat"
    assert context.env_vars["target_task_agent_id"] == "session-1"
    assert context.env_vars["parent_task_agent_type"] == "chat"
    assert context.env_vars["parent_task_agent_id"] == "session-1"


def test_chat_planning_service_context_targets_session_chat_agent() -> None:
    service = ChatPlanningService(
        agent_id="user-1",
        runtime_key="chat:user-1",
        context_service=SimpleNamespace(),
        prompt_service=SimpleNamespace(),
        context_assembler=SimpleNamespace(),
        tool_registry=ToolRegistry(),
        parent_task_agent_type="chat",
    )

    context = service._build_agent_tool_context("user-1", "session-1")

    assert context.env_vars["target_task_agent_type"] == "chat"
    assert context.env_vars["target_task_agent_id"] == "session-1"
    assert context.env_vars["parent_task_agent_type"] == "chat"
    assert context.env_vars["parent_task_agent_id"] == "session-1"


def test_chat_planning_service_context_uses_explicit_workspace_root() -> None:
    service = ChatPlanningService(
        agent_id="user-1",
        runtime_key="chat:user-1",
        context_service=SimpleNamespace(),
        prompt_service=SimpleNamespace(),
        context_assembler=SimpleNamespace(),
        tool_registry=ToolRegistry(),
        parent_task_agent_type="chat",
    )

    context = service._build_agent_tool_context(
        "user-1",
        "session-1",
        workspace_root="/tmp/magi",
    )

    assert context.workspace == "/tmp/magi"


@pytest.mark.asyncio
async def test_task_orchestrator_launch_workers_targets_session_chat_agent_in_payload() -> None:
    registry = _RecordingExecuteToolRegistry(ToolResult(success=True, data={"worker_ids": ["worker-1"]}))
    orchestrator = TaskOrchestrator(
        runtime_key="chat:user-1",
        tool_registry=registry,  # type: ignore[arg-type]
        plan_subtasks=_fake_plan_subtasks,
        aggregate_orchestration=_fake_aggregate,
        register_user_message=_fake_register_user_message,
        parent_task_agent_type="chat",
    )

    class _FakeStore:
        async def save_orchestration(self, state) -> None:  # type: ignore[no-untyped-def]
            _ = state

    orchestrator._orchestration_store = _FakeStore()
    from magi.agent.orchestration import SubtaskDefinition, TaskOrchestrationState

    state = TaskOrchestrationState(
        orchestration_id="orch-1",
        user_id="user-1",
        session_id="session-1",
        root_user_message="analyze repo",
        planner="task_agent",
        turn_id="turn-1",
        subtasks=[
            SubtaskDefinition(
                subtask_id="subtask-1",
                description="Inspect backend",
                subagent_type="CodeExplore",
                prompt="Inspect backend",
            )
        ],
    )

    error = await orchestrator._launch_workers(state)

    assert error is None
    assert len(registry.calls) == 1
    name, payload, context = registry.calls[0]
    assert name == "agent"
    assert payload["target_task_agent_type"] == "chat"
    assert payload["target_task_agent_id"] == "session-1"
    assert payload["workers"][0]["parent_task_agent_id"] == "session-1"
    assert payload["workers"][0]["target_task_agent_id"] == "session-1"
    assert context.env_vars["target_task_agent_id"] == "session-1"


@pytest.mark.asyncio
async def test_chat_planning_service_plan_worker_targets_session_chat_agent_in_payload() -> None:
    registry = _RecordingExecuteToolRegistry(
        ToolResult(
            success=True,
            data={
                "result": {
                    "summary": "plan",
                    "subtasks": [
                        {
                            "description": "Inspect backend",
                            "subagent_type": "CodeExplore",
                            "prompt": "Inspect backend",
                            "parallel_group": "group-a",
                        }
                    ],
                }
            },
        )
    )
    service = ChatPlanningService(
        agent_id="user-1",
        runtime_key="chat:user-1",
        context_service=SimpleNamespace(),
        prompt_service=SimpleNamespace(),
        context_assembler=SimpleNamespace(),
        tool_registry=registry,  # type: ignore[arg-type]
        parent_task_agent_type="chat",
    )

    plan = await service._plan_with_plan_worker(
        user_message="analyze repo",
        user_id="user-1",
        session_id="session-1",
    )

    assert plan is not None
    assert len(registry.calls) == 1
    name, payload, context = registry.calls[0]
    assert name == "agent"
    assert payload["target_task_agent_type"] == "chat"
    assert payload["target_task_agent_id"] == "session-1"
    assert payload["parent_task_agent_id"] == "session-1"
    assert "Start from the most concrete likely anchor or owning code path" in payload["prompt"]
    assert "Avoid generic subtasks that only gather context or summarize risks" in payload["prompt"]
    assert "# Tool Guidance" in payload["prompt"]
    assert context.env_vars["target_task_agent_id"] == "session-1"


@pytest.mark.asyncio
async def test_chat_planning_service_plan_worker_uses_explicit_workspace_root() -> None:
    registry = _RecordingExecuteToolRegistry(
        ToolResult(
            success=True,
            data={
                "result": {
                    "summary": "plan",
                    "subtasks": [
                        {
                            "description": "Inspect backend",
                            "subagent_type": "CodeExplore",
                            "prompt": "Inspect backend",
                            "parallel_group": "group-a",
                        }
                    ],
                }
            },
        )
    )
    service = ChatPlanningService(
        agent_id="user-1",
        runtime_key="chat:user-1",
        context_service=SimpleNamespace(),
        prompt_service=SimpleNamespace(),
        context_assembler=SimpleNamespace(),
        tool_registry=registry,  # type: ignore[arg-type]
        parent_task_agent_type="chat",
    )

    plan = await service._plan_with_plan_worker(
        user_message="analyze repo",
        user_id="user-1",
        session_id="session-1",
        workspace_root="/tmp/magi",
    )

    assert plan is not None
    _, _, context = registry.calls[0]
    assert context.workspace == "/tmp/magi"


def test_chat_planning_service_generic_fallback_and_leaf_prompt_emphasize_anchor_first_execution() -> None:
    service = ChatPlanningService(
        agent_id="user-1",
        runtime_key="chat:user-1",
        context_service=SimpleNamespace(),
        prompt_service=SimpleNamespace(),
        context_assembler=SimpleNamespace(),
        tool_registry=_registry_with_file_tools(),
        parent_task_agent_type="chat",
    )

    subtasks = service._fallback_subtask_plan(
        "分析检索链路",
        "CodeExplore",
        request_profile="generic",
    )

    assert [item.description for item in subtasks] == [
        "Locate the primary anchor",
        "Trace the owning implementation path",
        "Validate gaps and edge cases",
    ]

    prompt = service._build_leaf_worker_prompt(
        root_user_message="分析检索链路",
        subtask_description=subtasks[0].description,
        subtask_prompt=subtasks[0].prompt,
        request_profile="generic",
    )

    assert "Start from the most concrete anchor available" in prompt
    assert "verify it exists in the current code before relying on it" in prompt
    assert "Prefer focused glob/grep/read steps over broad repository scans" in prompt
    assert "# Tool Guidance" in prompt


@pytest.mark.asyncio
async def test_chat_planning_does_not_decompose_after_task_budget_exhaustion() -> None:
    from magi.agent.execution.task_budget import TaskBudgetExceeded

    class _ExhaustedPromptService:
        async def call_llm(self, **_kwargs):  # type: ignore[no-untyped-def]
            raise TaskBudgetExceeded(
                resource="llm_calls",
                limit=1,
                used=1,
                requested=1,
            )

    service = ChatPlanningService(
        agent_id="user-1",
        runtime_key="chat:user-1",
        context_service=SimpleNamespace(),
        prompt_service=_ExhaustedPromptService(),
        context_assembler=SimpleNamespace(),
        tool_registry=_registry_with_file_tools(),
        parent_task_agent_type="chat",
    )

    with pytest.raises(TaskBudgetExceeded, match="llm_calls"):
        await service.generate_subtask_plan(
            user_message="Analyze task orchestration",
            history=[],
            orchestration_plan=OrchestrationPlan(
                mode="decompose",
                default_leaf_type="CodeExplore",
                allow_parallel=True,
            ),
            user_id="user-1",
            session_id="session-1",
        )


@pytest.mark.asyncio
async def test_chat_planning_service_mixed_evidence_prompt_preserves_external_leaf_and_drops_synthesis() -> None:
    captured: dict[str, object] = {}

    class _FakePromptService:
        async def call_llm(self, **kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return (
                '{"summary":"Mixed evidence plan","subtasks":['
                '{"description":"Inspect Magi memory modules","subagent_type":"CodeExplore","prompt":"Inspect backend/src/magi/memory module boundaries and storage paths","parallel_group":"g1"},'
                '{"description":"Research Hindsight public docs","subagent_type":"general-purpose","prompt":"Search official documentation and public sources for Hindsight memory architecture. Collect source links and dates.","parallel_group":"g1"},'
                '{"description":"Synthesize sibling findings","subagent_type":"CodeExplore","prompt":"Compare the findings from other subtasks and write the final answer for the user","parallel_group":"g2"}'
                ']}'
            )

    service = ChatPlanningService(
        agent_id="user-1",
        runtime_key="chat:user-1",
        context_service=SimpleNamespace(),
        prompt_service=_FakePromptService(),
        context_assembler=SimpleNamespace(),
        tool_registry=_registry_with_file_tools(),
        parent_task_agent_type="chat",
    )

    plan = await service.generate_subtask_plan(
        user_message="详细对比一下 magi 和 Hindsight 的 memory architecture",
        history=[],
        orchestration_plan=OrchestrationPlan(
            mode="decompose", default_leaf_type="CodeExplore", allow_parallel=True
        ),
        user_id="user-1",
        session_id="session-1",
        workspace_root="/tmp/magi",
    )

    planning_message = str(captured["messages"][0]["content"])
    assert planning_message.startswith("# Planning Brief")
    assert "## Workspace Context" in planning_message
    assert "- Workspace root: /tmp/magi" in planning_message
    assert "- Workspace name: magi" in planning_message
    assert "## Requirements" in planning_message
    assert "split the plan by evidence source" in planning_message
    assert "## Task Hints" in planning_message
    assert [item.description for item in plan.subtasks] == [
        "Inspect Magi memory modules",
        "Research Hindsight public docs",
    ]
    assert [item.subagent_type for item in plan.subtasks] == ["CodeExplore", "general-purpose"]
    assert "do not assume local files exist; use external discovery first" in plan.subtasks[1].prompt
    assert "do not depend on sibling worker outputs" in plan.subtasks[1].prompt


@pytest.mark.asyncio
async def test_chat_planning_service_routes_local_travel_subtasks_to_general_worker() -> None:
    class _FakePromptService:
        async def call_llm(self, **kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs
            return (
                '{"summary":"Hangzhou itinerary plan","subtasks":['
                '{"description":"筛选杭州适合平地游览、不爬山的景点","subagent_type":"CodeExplore","prompt":"查找适合平地游览的杭州景点，保留开放时间和交通信息","parallel_group":"g1"},'
                '{"description":"查询杭州西站地铁交通及前往市区景点的路线","subagent_type":"CodeExplore","prompt":"查询杭州西站到西湖和运河景点的地铁换乘路线","parallel_group":"g1"},'
                '{"description":"推荐杭州适合晚上7点聚餐的餐厅或商圈","subagent_type":"CodeExplore","prompt":"查询适合晚餐聚餐的餐厅或商圈","parallel_group":"g1"}'
                "]}"
            )

    service = ChatPlanningService(
        agent_id="user-1",
        runtime_key="chat:user-1",
        context_service=SimpleNamespace(),
        prompt_service=_FakePromptService(),
        context_assembler=SimpleNamespace(),
        tool_registry=_registry_with_file_tools(),
        parent_task_agent_type="chat",
    )

    plan = await service.generate_subtask_plan(
        user_message="我不怎么运动，帮我安排明天杭州一天行程，包括地铁和晚餐商圈",
        history=[],
        orchestration_plan=OrchestrationPlan(
            mode="decompose", default_leaf_type="CodeExplore", allow_parallel=True
        ),
        user_id="user-1",
        session_id="session-1",
        workspace_root="/tmp/magi",
    )

    assert [item.subagent_type for item in plan.subtasks] == [
        "general-purpose",
        "general-purpose",
        "general-purpose",
    ]
    assert (
        "do not assume local files exist; use external discovery first" in plan.subtasks[0].prompt
    )
    assert "When you reference external evidence" in plan.subtasks[1].prompt


def test_chat_prompt_service_aggregation_prompt_uses_request_shaped_axes() -> None:
    service = ChatPromptService()

    prompt = service.build_aggregation_system_prompt(
        base_system_prompt="BASE SYSTEM PROMPT",
        state=SimpleNamespace(root_user_message="Compare Magi and Hindsight memory architecture"),
        payload={
            "user_request": "Compare Magi and Hindsight memory architecture",
            "planner": "task_agent",
            "completed_subtasks": [{"description": "Inspect Magi memory modules", "result": {}}],
            "failed_subtasks": [{"description": "Research Hindsight public docs", "failure_reason": "FAILED"}],
        },
    )

    assert "# Aggregation Task" in prompt
    assert "This is the final analysis synthesis step, not a casual back-and-forth chat turn." in prompt
    assert "## Internal Evidence Dossier" not in prompt
    assert "First infer the main analysis axes from the user's request and the completed evidence" in prompt
    assert "For comparison requests, prefer the strongest dimensions of difference" in prompt
    assert "explicitly absorb the key findings, evidence, and trade-offs from the completed subtasks" in prompt
    assert "usually cover multiple evidence-backed dimensions" in prompt
    assert "make their correspondence and evidence asymmetry explicit" in prompt
    assert "Do not let failed subtasks erase or outweigh richer completed findings" in prompt
    assert "do not force a fixed template" in prompt
    assert "Internal results (JSON)" not in prompt

    messages = service.build_aggregation_messages(
        history_messages=[{"role": "user", "content": "previous turn"}],
        state=SimpleNamespace(root_user_message="Compare Magi and Hindsight memory architecture"),
        payload={
            "user_request": "Compare Magi and Hindsight memory architecture",
            "planner": "task_agent",
            "completed_subtasks": [{"description": "Inspect Magi memory modules", "result": {}}],
            "failed_subtasks": [
                {
                    "description": "Research Hindsight public docs",
                    "failure_reason": "ALL_TOOLS_FAILED",
                    "failure_details": {
                        "tool_failures": [
                            {
                                "tool_name": "web-search",
                                "error_code": "PROVIDER_CHALLENGE",
                                "error": "DuckDuckGo challenge",
                                "diagnostics": {
                                    "next_action": "ask_user_to_configure_search_provider",
                                    "user_message_template": "DuckDuckGo hit an anti-bot check.",
                                },
                            }
                        ]
                    },
                }
            ],
        },
    )

    assert messages[0] == {"role": "user", "content": "previous turn"}
    aggregation_input = messages[-1]["content"]
    assert "## Original User Request" in aggregation_input
    assert "## Internal Evidence Dossier" in aggregation_input
    assert "Tool failure: web-search | PROVIDER_CHALLENGE | DuckDuckGo challenge" in aggregation_input
    assert "Suggested user-facing explanation: DuckDuckGo hit an anti-bot check." in aggregation_input


def test_worker_update_payload_preserves_tool_failures_for_aggregation() -> None:
    payload = WorkerUpdatePayload.from_dict(
        {
            "user_id": "u1",
            "session_id": "s1",
            "worker_id": "worker-1",
            "stage": "failed",
            "orchestration_id": "orch-1",
            "subtask_id": "subtask-1",
            "failure_reason": "ALL_TOOLS_FAILED",
            "error_text": "ALL_TOOLS_FAILED",
            "tool_failures": [
                {
                    "tool_name": "web-search",
                    "error_code": "PROVIDER_NOT_CONFIGURED",
                    "error": "Requested web search provider Brave Search is not configured.",
                    "diagnostics": {"requested_provider": "brave", "retryable": False},
                }
            ],
        },
        fallback_user_id="fallback",
    )

    assert payload.failure_reason == "ALL_TOOLS_FAILED"
    assert payload.error_text == "ALL_TOOLS_FAILED"
    assert payload.tool_failures[0]["tool_name"] == "web-search"
    assert payload.tool_failures[0]["diagnostics"]["requested_provider"] == "brave"


def test_chat_aggregation_payload_includes_failed_subtask_diagnostics() -> None:
    service = ChatPromptService()
    state = SimpleNamespace(
        root_user_message="安排杭州行程",
        planner="task_agent",
        subtasks=[
            SimpleNamespace(
                subtask_id="subtask-1",
                description="查询杭州地铁接驳",
                status="failed",
                worker_result=None,
                failure_reason="ALL_TOOLS_FAILED",
                failure_details={
                    "tool_failures": [
                        {
                            "tool_name": "web-search",
                            "error_code": "PROVIDER_CHALLENGE",
                            "error": "DuckDuckGo challenge",
                        }
                    ]
                },
                attempt_count=1,
            )
        ],
    )

    payload = service.build_aggregation_payload(state)

    assert payload["failed_subtasks"][0]["failure_reason"] == "ALL_TOOLS_FAILED"
    assert payload["failed_subtasks"][0]["failure_details"]["tool_failures"][0]["error_code"] == "PROVIDER_CHALLENGE"


@pytest.mark.asyncio
async def test_function_calling_agent_tool_treats_blank_session_id_as_missing() -> None:
    registry = _RecordingExecuteToolRegistry(ToolResult(success=True, data={"worker_id": "worker-1"}))
    orchestrator = FunctionCallingOrchestrator(
        tool_registry=registry,  # type: ignore[arg-type]
        llm_adapter=_DummyLLMAdapter(),
    )

    result = await orchestrator._execute_tool_call(
        tool_call=ToolCall(
            id="call-1",
            name="agent",
            arguments={
                "action": "launch",
                "description": "Inspect backend",
                "prompt": "Inspect backend",
            },
        ),
        user_id="user-1",
        session_id="   ",
        turn_id="turn-1",
        execution_preset="planning",
        execution_agent_id="chat:user-1",
        execution_workspace="/tmp",
    )

    assert result.success is True
    assert len(registry.calls) == 1
    _, _, context = registry.calls[0]
    assert context.env_vars["target_task_agent_id"] == "user-1"
    assert context.env_vars["session_id"] == "   "


@pytest.mark.asyncio
async def test_explore_completion_payload_targets_chat_session() -> None:
    manager = _RecordingTaskAgentManager()
    service = ExplorePostProcessService(get_task_agent_manager=lambda: manager)
    context = ExploreRuntimeContext(
        latest_fact=FactRecord(
            agent_id="explore:user-1",
            event_type="EXPLORE_TASK_REQUEST",
            payload={"user_id": "user-1", "session_id": "session-1", "content": "analyze repo"},
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
        latest_user_message="analyze repo",
        incoming_fact_kind=IncomingFactKind.EXPLORE_TASK_REQUEST,
        latest_payload=UserMessagePayload(user_id="user-1", session_id="session-1", content="analyze repo"),
        upstream_task_agent_type="chat",
        upstream_task_agent_id="session-1",
        root_turn_id="turn-root",
        user_message_generation=7,
    )

    await service.handle(
        context,
        ExecutionResult(
            mode=ExecutionMode.ORCHESTRATION_UPDATE,
            response_text="# Dossier",
            root_user_message="analyze repo",
            correlation_id="corr-1",
            turn_id="turn-1",
        ),
    )

    assert len(manager.calls) == 1
    agent_type, agent_id, fact = manager.calls[0]
    assert agent_type == "chat"
    assert agent_id == "session-1"
    assert fact.agent_id == "chat:session-1"
    assert fact.payload["target_task_agent_type"] == "chat"
    assert fact.payload["target_task_agent_id"] == "session-1"
    assert fact.payload["root_turn_id"] == "turn-root"
    assert fact.user_message_generation == 7


@pytest.mark.asyncio
async def test_worker_completion_payload_targets_chat_session() -> None:
    manager = _RecordingTaskAgentManager()
    worker_manager = WorkerAgentManager()
    worker_manager._task_agent_manager = manager
    now = time.time()
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
        created_at=now,
        updated_at=now,
        status="completed",
    )

    await worker_manager._publish_worker_fact(
        run_state,
        WORKER_AGENT_COMPLETED,
        {
            "worker_result": {
                "result_status": "success",
                "summary": "Backend analyzed",
                "findings": [],
                "evidence": [],
                "gaps": [],
                "next_steps": [],
                "failure_reason": None,
            }
        },
    )

    assert len(manager.calls) == 1
    agent_type, agent_id, fact = manager.calls[0]
    assert agent_type == "chat"
    assert agent_id == "session-1"
    assert fact.payload["target_task_agent_type"] == "chat"
    assert fact.payload["target_task_agent_id"] == "session-1"
