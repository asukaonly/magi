from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from magi.agent.execution.function_calling.failures import FunctionCallingFailureMixin
from magi.agent.execution.function_calling.llm import _prepare_llm_call
from magi.agent.execution.function_calling.orchestrator import (
    FunctionCallingOrchestrator,
)
from magi.agent.execution.function_calling.types import ExecutionOutcome
from magi.agent.execution.task_budget import (
    DEFAULT_TASK_MAX_LLM_CALLS,
    TaskBudgetExceeded,
    consume_task_llm_calls,
    current_task_budget,
    prepay_task_llm_calls,
    release_prepaid_task_llm_calls,
    reserve_task_llm_calls,
    task_execution_budget_scope,
)
from magi.agent.turn_input import UserTurnInput
from magi.llm.provider_bridge import ProviderResponse


@pytest.mark.asyncio
async def test_parallel_reservations_do_not_oversell_llm_budget() -> None:
    async with task_execution_budget_scope(max_llm_calls=3) as budget:

        async def reserve_once() -> bool:
            try:
                await reserve_task_llm_calls()
            except TaskBudgetExceeded:
                return False
            return True

        outcomes = await asyncio.gather(*(reserve_once() for _ in range(5)))

    assert outcomes.count(True) == 3
    assert outcomes.count(False) == 2
    assert budget.llm_calls == 3


@pytest.mark.asyncio
async def test_nested_scope_reuses_parent_budget() -> None:
    async with task_execution_budget_scope(max_llm_calls=2) as parent:
        async with task_execution_budget_scope(max_llm_calls=99) as nested:
            assert nested is parent
            await reserve_task_llm_calls()

    assert parent.max_llm_calls == 2
    assert parent.llm_calls == 1
    assert current_task_budget() is None


@pytest.mark.asyncio
async def test_nested_scope_releases_only_its_own_prepaid_calls() -> None:
    async with task_execution_budget_scope(max_llm_calls=2) as budget:
        await prepay_task_llm_calls()

        async with task_execution_budget_scope():
            await prepay_task_llm_calls()
            assert budget.llm_calls == 2
            assert await release_prepaid_task_llm_calls() == 1

        assert budget.llm_calls == 1
        await consume_task_llm_calls()

    assert budget.llm_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("max_iterations", [1, 50])
async def test_orchestrator_root_budget_is_independent_from_local_iteration_limit(
    max_iterations: int,
) -> None:
    class _ProbeOrchestrator:
        execute_with_tools = FunctionCallingOrchestrator.execute_with_tools
        _resolve_control = staticmethod(FunctionCallingOrchestrator._resolve_control)

        async def _execute_with_tools_impl(self, **kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs
            budget = current_task_budget()
            assert budget is not None
            await reserve_task_llm_calls(2)
            return ExecutionOutcome(
                status="completed",
                content=str(budget.max_llm_calls),
            )

    outcome = await _ProbeOrchestrator().execute_with_tools(
        turn=UserTurnInput(text="probe"),
        system_prompt="",
        selected_tools=[],
        user_id="u-budget",
        max_iterations=max_iterations,
    )

    assert outcome.content == str(DEFAULT_TASK_MAX_LLM_CALLS)


@pytest.mark.asyncio
async def test_independent_root_tasks_receive_isolated_budgets() -> None:
    ready = asyncio.Event()

    async def run_root() -> object:
        async with task_execution_budget_scope() as budget:
            await ready.wait()
            return budget

    first = asyncio.create_task(run_root())
    second = asyncio.create_task(run_root())
    await asyncio.sleep(0)
    ready.set()

    first_budget, second_budget = await asyncio.gather(first, second)

    assert first_budget is not second_budget


@pytest.mark.asyncio
async def test_unconfigured_launch_does_not_consume_worker_budget() -> None:
    from magi.agent.runtime_tools import AgentTool
    from magi.tools.schema import ToolExecutionContext

    tool = AgentTool()
    context = ToolExecutionContext(
        agent_id="chat:u-chat",
        workspace="/tmp",
        env_vars={"user_id": "u-chat", "session_id": "s-chat"},
        permissions=["authenticated"],
    )

    async with task_execution_budget_scope(max_worker_launches=1) as budget:
        result = await tool.execute(
            parameters={
                "action": "launch",
                "subagent_type": "CodeExplore",
                "description": "inspect startup",
                "prompt": "This worker cannot start before configuration.",
                "run_in_background": True,
            },
            context=context,
        )
        await budget.reserve_worker_launches()

    assert result.success is False
    assert result.error_code == "EXECUTION_ERROR"
    assert budget.worker_launches == 1


@pytest.mark.asyncio
async def test_background_child_keeps_shared_budget_after_parent_scope_exits() -> None:
    continue_child = asyncio.Event()

    async def child() -> object | None:
        await continue_child.wait()
        budget = current_task_budget()
        await reserve_task_llm_calls()
        return budget

    async with task_execution_budget_scope(max_llm_calls=2) as parent:
        task = asyncio.create_task(child())

    continue_child.set()
    child_budget = await task

    assert child_budget is parent
    assert parent.llm_calls == 1
    assert current_task_budget() is None


@pytest.mark.asyncio
async def test_background_child_cannot_duplicate_parent_prepaid_call() -> None:
    async with task_execution_budget_scope(max_llm_calls=2) as budget:
        await prepay_task_llm_calls()

        child = asyncio.create_task(consume_task_llm_calls())
        await child
        await consume_task_llm_calls()

    assert budget.llm_calls == 2


@pytest.mark.asyncio
async def test_repeated_prepayment_reuses_the_same_parent_continuation() -> None:
    async with task_execution_budget_scope(max_llm_calls=2) as budget:
        await prepay_task_llm_calls()
        await prepay_task_llm_calls()
        await consume_task_llm_calls()

    assert budget.llm_calls == 1


@pytest.mark.asyncio
async def test_completed_branches_release_unused_final_call_headroom() -> None:
    async def finish_after_one_call() -> None:
        await prepay_task_llm_calls(2)
        await consume_task_llm_calls()
        assert await release_prepaid_task_llm_calls() == 1

    async with task_execution_budget_scope(max_llm_calls=30) as budget:
        await asyncio.gather(*(finish_after_one_call() for _ in range(8)))
        assert budget.llm_calls == 8
        for _ in range(22):
            await consume_task_llm_calls()

    assert budget.llm_calls == 30


@pytest.mark.asyncio
async def test_ambiguous_durable_refund_is_not_retried() -> None:
    class _AmbiguousReleaseStore:
        def __init__(self) -> None:
            self.llm_calls = 0
            self.release_calls = 0

        async def ensure_task_execution_budget(self, **_kwargs):  # type: ignore[no-untyped-def]
            return (2, self.llm_calls, 8, 0)

        async def reserve_task_execution_budget(self, **kwargs):  # type: ignore[no-untyped-def]
            self.llm_calls += int(kwargs["count"])
            return (True, 2, self.llm_calls, 8, 0)

        async def release_task_execution_llm_calls(self, **kwargs):  # type: ignore[no-untyped-def]
            self.release_calls += 1
            self.llm_calls -= int(kwargs["count"])
            raise RuntimeError("connection closed after commit")

    store = _AmbiguousReleaseStore()
    async with task_execution_budget_scope(
        root_turn_id="turn-root",
        store=store,
        max_llm_calls=2,
    ):
        await prepay_task_llm_calls()
        with pytest.raises(RuntimeError, match="after commit"):
            await release_prepaid_task_llm_calls()

    assert store.release_calls == 1
    assert store.llm_calls == 0


@pytest.mark.asyncio
async def test_common_llm_prepare_boundary_reserves_calls() -> None:
    class _FakeLlm:
        model_name = "fake-model"

    class _Owner:
        @staticmethod
        def _resolve_llm() -> _FakeLlm:
            return _FakeLlm()

    async with task_execution_budget_scope(max_llm_calls=1):
        await _prepare_llm_call(_Owner(), None)
        with pytest.raises(TaskBudgetExceeded, match="llm_calls"):
            await _prepare_llm_call(_Owner(), None)


@pytest.mark.asyncio
async def test_llm_resolution_failure_does_not_consume_budget() -> None:
    class _Owner:
        @staticmethod
        def _resolve_llm() -> None:
            raise ValueError("provider is not configured")

    async with task_execution_budget_scope(max_llm_calls=1) as budget:
        with pytest.raises(ValueError, match="provider is not configured"):
            await _prepare_llm_call(_Owner(), None)

    assert budget.llm_calls == 0


@pytest.mark.asyncio
async def test_last_budget_slot_forces_a_tool_turn_to_finalize() -> None:
    class _ToolRegistry:
        @staticmethod
        def is_skill(name: str) -> bool:
            _ = name
            return False

        @staticmethod
        def get_tool_info(name: str) -> dict[str, object]:
            return {
                "name": name,
                "description": "Demo tool",
                "parameters": [],
            }

    adapter = SimpleNamespace(model_name="fake-model", provider_name="fake-provider")
    orchestrator = FunctionCallingOrchestrator(
        llm_adapter=adapter,  # type: ignore[arg-type]
        tool_registry=_ToolRegistry(),  # type: ignore[arg-type]
    )
    provider_calls: list[str] = []
    final_request: dict[str, object] = {}

    async def _with_tools(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        provider_calls.append("tools")
        return ProviderResponse(content="should not run")

    async def _without_tools(**kwargs):  # type: ignore[no-untyped-def]
        final_request.update(kwargs)
        provider_calls.append("final")
        return ProviderResponse(content='{"result_status":"success"}')

    orchestrator.provider_bridge.chat_with_tools = _with_tools  # type: ignore[method-assign]
    orchestrator.provider_bridge.chat_response = _without_tools  # type: ignore[method-assign]

    async with task_execution_budget_scope(max_llm_calls=1) as budget:
        result = await orchestrator.execute_with_tools(
            turn=UserTurnInput(text="Use a tool if needed."),
            system_prompt="Finish the task.",
            selected_tools=["demo"],
            user_id="budget-user",
            final_response_json_mode=True,
        )

    assert result.content == '{"result_status":"success"}'
    assert provider_calls == ["final"]
    assert final_request["json_mode"] is True
    messages = final_request["messages"]
    assert isinstance(messages, list)
    assert "Do not call tools or output any tool markup" in messages[-1]["content"]
    assert budget.llm_calls == 1


@pytest.mark.asyncio
async def test_task_agent_direct_and_planning_calls_share_budget(monkeypatch) -> None:
    from magi.agent.task_agents.common.llm_service import TaskAgentLLMService

    direct_service = TaskAgentLLMService(llm_adapter=None, logger_name="direct-test")
    planning_service = TaskAgentLLMService(llm_adapter=None, logger_name="planner-test")
    direct_service._llm = SimpleNamespace(model_name="fake-direct")
    planning_service._llm = SimpleNamespace(model_name="fake-planner")
    provider_calls: list[str] = []

    async def _direct_response(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        provider_calls.append("direct")
        return SimpleNamespace(content="direct response", metadata={})

    async def _planning_response(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        provider_calls.append("planning")
        return SimpleNamespace(content="planning response", metadata={})

    monkeypatch.setattr(direct_service, "_call_provider_response", _direct_response)
    monkeypatch.setattr(planning_service, "_call_provider_response", _planning_response)

    async with task_execution_budget_scope(max_llm_calls=1):
        response = await direct_service.call(system_prompt="", messages=[])
        with pytest.raises(TaskBudgetExceeded, match="llm_calls"):
            await planning_service.call(system_prompt="", messages=[])

    assert response == "direct response"
    assert provider_calls == ["direct"]


@pytest.mark.asyncio
async def test_task_agent_stream_reserves_before_opening_provider(monkeypatch) -> None:
    from magi.agent.task_agents.common.llm_service import TaskAgentLLMService
    from magi.llm.streaming_events import LLMStreamEvent

    service = TaskAgentLLMService(llm_adapter=None, logger_name="stream-test")
    service._llm = SimpleNamespace(model_name="fake-stream")
    opened_streams = 0

    def _open_stream(**kwargs):  # type: ignore[no-untyped-def]
        nonlocal opened_streams
        _ = kwargs
        opened_streams += 1

        async def _events():
            yield LLMStreamEvent(kind="text_delta", text="ok")

        return _events()

    monkeypatch.setattr(service, "_open_provider_stream", _open_stream)

    async with task_execution_budget_scope(max_llm_calls=1):
        first = [event async for event in service.call_stream(system_prompt="", messages=[])]
        with pytest.raises(TaskBudgetExceeded, match="llm_calls"):
            async for _ in service.call_stream(system_prompt="", messages=[]):
                pass

    assert [event.text for event in first] == ["ok"]
    assert opened_streams == 1


@pytest.mark.asyncio
async def test_task_agent_execution_engine_binds_root_budget() -> None:
    from magi.agent.run.execution_engine import TaskAgentExecutionEngine
    from magi.agent.task_agents.common.contracts import ExecutionMode, ExecutionResult

    class _Handler:
        observed_budget = None

        async def execute(self, request):  # type: ignore[no-untyped-def]
            _ = request
            self.observed_budget = current_task_budget()
            return ExecutionResult(
                mode=ExecutionMode.DIRECT_LLM,
                response_text="done",
            )

    class _Registry:
        def __init__(self, handler: _Handler) -> None:
            self._handler = handler

        def get(self, mode):  # type: ignore[no-untyped-def]
            _ = mode
            return self._handler

    handler = _Handler()
    engine = TaskAgentExecutionEngine(handler_registry=_Registry(handler))
    request = SimpleNamespace(
        mode=ExecutionMode.DIRECT_LLM,
        intent=SimpleNamespace(route_decision=None),
    )

    outcome = await engine.execute(request)  # type: ignore[arg-type]

    assert outcome.result is not None
    assert handler.observed_budget is not None
    assert current_task_budget() is None


@pytest.mark.asyncio
async def test_explore_planning_and_workers_share_one_root_budget() -> None:
    from magi.agent.task_agents.explore_task_agent import ExploreTaskAgent

    observed_budgets: list[object | None] = []

    async def _charge_branch() -> None:
        observed_budgets.append(current_task_budget())
        await consume_task_llm_calls()

    class _Handler:
        @staticmethod
        async def build_request(request):  # type: ignore[no-untyped-def]
            return request

        @staticmethod
        async def execute(request):  # type: ignore[no-untyped-def]
            _ = request
            await asyncio.create_task(_charge_branch(), name="explore-plan-probe")
            await asyncio.create_task(_charge_branch(), name="explore-worker-probe")
            return "done"

    class _Registry:
        @staticmethod
        def get(mode):  # type: ignore[no-untyped-def]
            _ = mode
            return _Handler()

    agent = ExploreTaskAgent.__new__(ExploreTaskAgent)
    agent._handler_registry = _Registry()  # type: ignore[assignment]

    result = await agent.call_llm(object(), SimpleNamespace(mode="probe"))

    assert result == "done"
    assert observed_budgets[0] is observed_budgets[1]
    assert observed_budgets[0] is not None
    assert observed_budgets[0].llm_calls == 2  # type: ignore[union-attr]
    assert current_task_budget() is None


@pytest.mark.asyncio
async def test_persistent_task_agent_actor_does_not_inherit_worker_budget() -> None:
    from magi.agent.run.execution_engine import TaskAgentExecutionEngine
    from magi.agent.runtime.contracts import FactRecord
    from magi.agent.runtime.task_agent import TaskAgent
    from magi.agent.task_agents.common.contracts import ExecutionMode

    observed_budgets: asyncio.Queue[object] = asyncio.Queue()

    class _Handler:
        @staticmethod
        async def execute(request):  # type: ignore[no-untyped-def]
            _ = request
            budget = current_task_budget()
            assert budget is not None
            await reserve_task_llm_calls()
            await observed_budgets.put(budget)
            return object()

    class _Registry:
        @staticmethod
        def get(mode):  # type: ignore[no-untyped-def]
            if mode != ExecutionMode.DIRECT_LLM:
                raise KeyError(mode)
            return _Handler()

    class _PersistentAgent(TaskAgent):
        def __init__(self) -> None:
            TaskAgent.__init__(self, agent_type="probe", agent_id="persistent")
            self._engine = TaskAgentExecutionEngine(handler_registry=_Registry())

        async def assemble_llm_params(self, context, intent_result, tool_result):  # type: ignore[no-untyped-def]
            _ = (context, intent_result, tool_result)
            return SimpleNamespace(
                mode=ExecutionMode.DIRECT_LLM,
                intent=SimpleNamespace(route_decision=None),
            )

        async def call_llm(self, context, llm_params):  # type: ignore[no-untyped-def]
            _ = context
            return (await self._engine.execute(llm_params)).result

        async def parse_result(self, context, raw_result):  # type: ignore[no-untyped-def]
            _ = (context, raw_result)

    agent = _PersistentAgent()
    try:
        async with task_execution_budget_scope(max_llm_calls=10) as worker_budget:
            await agent.start(event_emitter=None)
            assert await agent.add_fact(
                FactRecord(agent_id="probe:persistent", event_type="first", payload={})
            )
            first_budget = await asyncio.wait_for(observed_budgets.get(), timeout=1)

        assert await agent.add_fact(
            FactRecord(agent_id="probe:persistent", event_type="second", payload={})
        )
        second_budget = await asyncio.wait_for(observed_budgets.get(), timeout=1)
    finally:
        await agent.stop()

    assert first_budget is not worker_budget
    assert second_budget is not worker_budget
    assert first_budget is not second_budget
    assert first_budget.llm_calls == 1  # type: ignore[union-attr]
    assert second_budget.llm_calls == 1  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_fork_skill_direct_call_does_not_consume_outer_reservation(
    monkeypatch,
) -> None:
    from magi.skills import subagent as subagent_module
    from magi.skills.schema import SkillContent, SkillFrontmatter
    from magi.skills.subagent import SkillSubagent

    provider_calls = 0

    class _Bridge:
        def __init__(self, llm) -> None:  # type: ignore[no-untyped-def]
            _ = llm

        async def chat(self, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal provider_calls
            _ = kwargs
            provider_calls += 1
            return "translated"

    monkeypatch.setattr(subagent_module, "LLMProviderBridge", _Bridge)
    skill = SkillContent(
        name="translate",
        frontmatter=SkillFrontmatter(
            name="translate",
            description="Translate text",
            context="fork",
        ),
        prompt_template="Translate the input.",
    )
    subagent = SkillSubagent(
        skill=skill,
        llm_adapter=object(),  # type: ignore[arg-type]
        llm_call_reserver=reserve_task_llm_calls,
    )

    async with task_execution_budget_scope(max_llm_calls=2) as budget:
        await prepay_task_llm_calls()
        result = await subagent.execute(
            user_message="hello",
            system_prompt="Translate the input.",
        )
        assert budget.llm_calls == 2
        await consume_task_llm_calls()

    assert result.success is True
    assert result.content == "translated"
    assert provider_calls == 1
    assert budget.llm_calls == 2


@pytest.mark.asyncio
async def test_context_compactor_reserves_each_summary_chunk(monkeypatch) -> None:
    from magi.agent.execution import context_compactor as compactor_module
    from magi.agent.execution.context_compactor import ContextCompactor
    from magi.llm.model_context import ModelContextProfile

    class _Bridge:
        def __init__(self, adapter) -> None:  # type: ignore[no-untyped-def]
            _ = adapter

        async def chat(self, **kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs
            return SimpleNamespace(content="summary")

    async def _two_chunk_summary(**kwargs):  # type: ignore[no-untyped-def]
        call_chunk = kwargs["call_chunk"]
        await call_chunk(SimpleNamespace(prompt="first", index=0, is_final=False))
        return await call_chunk(SimpleNamespace(prompt="second", index=1, is_final=True))

    monkeypatch.setattr(compactor_module, "LLMProviderBridge", _Bridge)
    monkeypatch.setattr(
        compactor_module,
        "generate_cumulative_summary",
        _two_chunk_summary,
    )
    compactor = ContextCompactor(context_window=4096)
    monkeypatch.setattr(
        compactor,
        "_resolve_summary_model",
        lambda: SimpleNamespace(
            adapter=object(),
            context=ModelContextProfile(
                provider_id="fake",
                model_id="fake",
                context_window=4096,
                max_output_tokens=512,
            ),
        ),
    )

    async with task_execution_budget_scope(max_llm_calls=1):
        with pytest.raises(TaskBudgetExceeded, match="llm_calls"):
            await compactor._call_summariser("summarize this")


@pytest.mark.asyncio
async def test_context_compactor_preserves_main_call_headroom(monkeypatch) -> None:
    from magi.agent.execution import context_compactor as compactor_module
    from magi.agent.execution.context_compactor import ContextCompactor
    from magi.llm.model_context import ModelContextProfile

    bridge_calls = 0

    class _Bridge:
        def __init__(self, adapter) -> None:  # type: ignore[no-untyped-def]
            _ = adapter

        async def chat(self, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal bridge_calls
            _ = kwargs
            bridge_calls += 1
            return SimpleNamespace(content="summary")

    async def _one_chunk_summary(**kwargs):  # type: ignore[no-untyped-def]
        return await kwargs["call_chunk"](
            SimpleNamespace(prompt="summary chunk", index=0, is_final=True)
        )

    monkeypatch.setattr(compactor_module, "LLMProviderBridge", _Bridge)
    monkeypatch.setattr(
        compactor_module,
        "generate_cumulative_summary",
        _one_chunk_summary,
    )
    compactor = ContextCompactor(
        scenario_llm_pool=object(),
        context_window=4096,
    )
    monkeypatch.setattr(
        compactor,
        "_resolve_summary_model",
        lambda: SimpleNamespace(
            adapter=object(),
            context=ModelContextProfile(
                provider_id="fake",
                model_id="fake",
                context_window=4096,
                max_output_tokens=512,
            ),
        ),
    )
    messages = [
        {"role": "user", "content": "older question"},
        {"role": "assistant", "content": "older answer"},
        {"role": "user", "content": "latest question"},
    ]

    class _MainCallOwner:
        @staticmethod
        def _resolve_llm() -> SimpleNamespace:
            return SimpleNamespace(model_name="fake-main")

    async with task_execution_budget_scope(max_llm_calls=1) as budget:
        result = await compactor.compact(messages, preserve_user_turns=True)
        assert bridge_calls == 0
        assert budget.llm_calls == 1
        await _prepare_llm_call(_MainCallOwner(), None)

    assert result.messages
    assert budget.llm_calls == 1


@pytest.mark.asyncio
async def test_background_agent_worker_inherits_parent_budget(
    monkeypatch,
    tmp_path,
) -> None:
    from magi.agent.runtime_tools import AgentTool
    from magi.agent.workers import worker_execution as worker_execution_module
    from magi.tools.schema import ToolExecutionContext

    release_worker = asyncio.Event()
    observed_budgets: list[object | None] = []

    class _FakeWorkerOrchestrator:
        def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs

        async def run(self, run_input):  # type: ignore[no-untyped-def]
            _ = run_input
            await release_worker.wait()
            observed_budgets.append(current_task_budget())
            await reserve_task_llm_calls()
            return ExecutionOutcome(
                status="completed",
                content=json.dumps(
                    {
                        "result_status": "success",
                        "summary": "worker completed",
                        "findings": [],
                        "evidence": [],
                        "records": [],
                        "gaps": [],
                        "next_steps": [],
                        "failure_reason": None,
                    }
                ),
                iterations=1,
            )

    class _FakeRegistry:
        @staticmethod
        def list_tools() -> list[str]:
            return []

    monkeypatch.setattr(
        worker_execution_module,
        "FunctionCallingOrchestrator",
        _FakeWorkerOrchestrator,
    )
    tool = AgentTool()
    tool.configure(
        llm_adapter=SimpleNamespace(model_name="fake-worker"),
        tool_registry_instance=_FakeRegistry(),  # type: ignore[arg-type]
    )
    context = ToolExecutionContext(
        agent_id="chat:u-budget",
        workspace=str(tmp_path),
        env_vars={"user_id": "u-budget", "session_id": "s-budget"},
        permissions=["authenticated"],
    )

    async with task_execution_budget_scope(
        max_llm_calls=2,
        max_worker_launches=1,
    ) as parent_budget:
        launched = await tool.execute(
            parameters={
                "action": "launch",
                "subagent_type": "general-purpose",
                "description": "verify budget context",
                "prompt": "Return a structured result.",
                "run_in_background": True,
            },
            context=context,
        )

    release_worker.set()
    awaited = await tool.execute(
        parameters={
            "action": "await",
            "worker_id": launched.data["worker_id"],
            "timeout_seconds": 2,
        },
        context=context,
    )

    assert launched.success is True
    assert awaited.success is True
    assert observed_budgets == [parent_budget]
    assert parent_budget.llm_calls == 1


@pytest.mark.asyncio
async def test_registry_worker_launch_reuses_parent_continuation_reservation(
    monkeypatch,
    tmp_path,
) -> None:
    from magi.agent.runtime_tools import AgentTool
    from magi.agent.workers import worker_execution as worker_execution_module
    from magi.tools.registry import ToolRegistry
    from magi.tools.schema import ToolExecutionContext

    class _BudgetConsumingWorker:
        def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs

        async def run(self, run_input):  # type: ignore[no-untyped-def]
            _ = run_input
            await reserve_task_llm_calls()
            return ExecutionOutcome(
                status="completed",
                content=json.dumps(
                    {
                        "result_status": "success",
                        "summary": "worker completed",
                        "findings": [],
                        "evidence": [],
                        "records": [],
                        "gaps": [],
                        "next_steps": [],
                        "failure_reason": None,
                    }
                ),
                iterations=1,
            )

    class _WorkerToolRegistry:
        @staticmethod
        def list_tools() -> list[str]:
            return []

    monkeypatch.setattr(
        worker_execution_module,
        "FunctionCallingOrchestrator",
        _BudgetConsumingWorker,
    )
    execution_registry = ToolRegistry()
    execution_registry.register(AgentTool)
    tool = execution_registry.get_tool("agent")
    assert isinstance(tool, AgentTool)
    tool.configure(
        llm_adapter=SimpleNamespace(model_name="fake-worker"),
        tool_registry_instance=_WorkerToolRegistry(),  # type: ignore[arg-type]
    )
    context = ToolExecutionContext(
        agent_id="chat:u-budget",
        workspace=str(tmp_path),
        env_vars={"user_id": "u-budget", "session_id": "s-budget"},
        permissions=["authenticated"],
    )

    async with task_execution_budget_scope(
        max_llm_calls=3,
        max_worker_launches=1,
    ) as budget:
        await prepay_task_llm_calls(2)
        await consume_task_llm_calls()
        result = await asyncio.create_task(
            execution_registry.execute(
                "agent",
                {
                    "action": "launch",
                    "subagent_type": "general-purpose",
                    "description": "consume worker budget",
                    "prompt": "Return a structured result.",
                    "run_in_background": False,
                },
                context,
            )
        )
        await consume_task_llm_calls()

    assert result.success is True
    assert budget.llm_calls == 3


def test_budget_exhaustion_has_specific_failure_bucket() -> None:
    class _FailureHost(FunctionCallingFailureMixin):
        _RATE_LIMIT_BACKOFF_SECONDS: tuple[float, ...] = ()

    failure = _FailureHost()._classify_exception_failure(
        TaskBudgetExceeded(
            resource="llm_calls",
            limit=1,
            used=1,
            requested=1,
        )
    )

    assert failure == "TASK_BUDGET_EXCEEDED"
