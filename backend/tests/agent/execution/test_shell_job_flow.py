from __future__ import annotations

import os
import json
from types import SimpleNamespace

import pytest

from agent.agent_run_helpers import run_agent
from agent.permission_helpers import AllowAllPermissionGateway
from magi.agent.execution.function_calling import FunctionCallingOrchestrator, ToolCall
from magi.agent.turn_input import UserTurnInput
from magi.tools.builtin.bash_tool import BashTool
from magi.tools.builtin.shell_job_tool import ShellJobTool
from magi.tools.registry import ToolRegistry


@pytest.mark.asyncio
@pytest.mark.skipif(os.name == "nt", reason="POSIX shell integration")
async def test_main_loop_observes_and_finishes_a_continued_shell_job(tmp_path, monkeypatch):
    monkeypatch.setenv("MAGI_CHILD_PROCESS_REGISTRY", str(tmp_path / "children.json"))
    registry = ToolRegistry()
    registry.register(BashTool)
    registry.register(ShellJobTool)
    shell = registry.get_tool("bash")
    host = FunctionCallingOrchestrator(
        tool_registry=registry,
        llm_adapter=SimpleNamespace(model_name="test", provider_name="test"),
        permission_gateway=AllowAllPermissionGateway(),
    )
    calls = 0

    def tool_response(call):
        return {"tool_calls": [call], "assistant_message": {
            "role": "assistant", "content": None, "tool_calls": [{
                "id": call.id, "type": "function", "function": {
                    "name": call.name, "arguments": json.dumps(call.arguments),
                },
            }],
        }}

    async def model(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return tool_response(ToolCall(id="start", name="bash", arguments={
                "command": "printf started; sleep 1.2; printf finished", "timeout": 1,
            }))
        if calls == 2:
            job_id = next(iter(shell.jobs._jobs))
            assert any(tool["function"]["name"] == "shell_job" for tool in kwargs["tools"])
            assert any(job_id in str(message.get("content")) for message in kwargs["messages"])
            return tool_response(ToolCall(id="wait", name="shell_job", arguments={
                "action": "wait", "job_id": job_id, "wait_seconds": 10,
            }))
        return {"content": "The command finished successfully.", "tool_calls": []}

    monkeypatch.setattr(host, "_call_llm_with_tools", model)
    try:
        outcome = await run_agent(
            host, turn=UserTurnInput(text="Run the check", attachments=[], user_id=None, session_id=None),
            system_prompt="Run the requested command and confirm its exit.", selected_tools=["bash"],
            user_id="user", session_id="session", turn_id="turn", execution_workspace=str(tmp_path),
        )
        assert outcome.status == "completed", outcome
        assert outcome.content == "The command finished successfully."
        assert calls == 3
        assert next(iter(shell.jobs._jobs.values())).status == "completed"
    finally:
        await shell.clear_user_content()


@pytest.mark.asyncio
@pytest.mark.parametrize("risk", ["read_only", "mutating"])
async def test_terminal_job_reader_failure_is_not_reported_as_still_running(tmp_path, risk):
    import asyncio
    from dataclasses import replace

    from magi.agent.execution.completion_gate import CompletionGate
    from magi.agent.execution.completion_policy import CompletionPolicy
    from magi.agent.execution.contracts import CompletionOutcome
    from magi.agent.execution.evidence import ToolExecutionEvidence
    from magi.tools.builtin._shell_jobs import ShellJobs
    from magi.tools.schema import ToolExecutionContext

    manager = ShellJobs("bash")
    release = asyncio.Event()

    async def failing_reader(**callbacks):
        callbacks["on_spawn"](999999)
        await release.wait()
        raise OSError("Output reader failed after process cleanup")

    context = ToolExecutionContext(
        agent_id="chat:session", workspace=str(tmp_path),
        env_vars={"user_id": "user", "session_id": "session"},
    )

    def evidence_for(name, result, effect):
        return ToolExecutionEvidence(
            tool_name=name, success=result.success, effect_class=effect,
            replay_policy="reconcilable", result=result.data, error_code=result.error_code,
        )

    try:
        started = await manager.start(
            command="check", context=context, background=False, risk_data={"risk_level": risk},
            wait_seconds=0.001, run=failing_reader, render=lambda result: result,
        )
        assert started.success and started.data["status"] == "running"
        evidence = [evidence_for("bash", started, "unknown")]
        release.set()
        await manager._jobs[started.data["job_id"]].task
        for action in ("wait", "poll", "stop"):
            result = await manager.control({"action": action, "job_id": started.data["job_id"]}, context)
            assert not result.success
            assert result.data["status"] == "failed"
            assert result.error_code == "EXECUTION_ERROR"
            evidence.append(evidence_for("shell_job", result, "local_write" if action == "stop" else "read_only"))
            if action == "wait":
                for field, value in (("job_id", "other"), ("shell_tool", "powershell")):
                    unrelated = replace(evidence[-1], result={**result.data, field: value})
                    assert CompletionGate().evaluate(
                        policy=CompletionPolicy(), evidence=[evidence[0], unrelated], repair_iterations=0
                    ).reason_code == "shell_job_pending"
                uncertain = replace(evidence[-1], error_code="TOOL_EFFECT_UNCERTAIN")
                assert CompletionGate().evaluate(
                    policy=CompletionPolicy(), evidence=[evidence[0], uncertain], repair_iterations=0
                ).reason_code == "uncertain_effect"
            decision = CompletionGate().evaluate(policy=CompletionPolicy(), evidence=evidence, repair_iterations=0)
            assert decision.reason_code != "shell_job_pending"
            if risk == "read_only":
                assert decision.outcome is CompletionOutcome.COMPLETE
            else:
                assert decision.outcome is CompletionOutcome.BLOCKED
                assert decision.reason_code == "uncertain_effect"
                prior_check = ToolExecutionEvidence(
                    tool_name="verify", success=True, effect_class="read_only", replay_policy="read_only",
                    result={"results": [{"path": "/workspace/a.py", "status": "pass", "verifier": "python", "content_sha256": "a" * 64}]},
                )
                assert CompletionGate().evaluate(
                    policy=CompletionPolicy(), evidence=[evidence[0], prior_check, evidence[-1]], repair_iterations=0
                ).reason_code == "uncertain_effect"
                validation_only = CompletionGate().evaluate(
                    policy=CompletionPolicy(require_effect_terminal_state=False), evidence=evidence, repair_iterations=0
                )
                assert validation_only.reason_code == "validation_required"
    finally:
        await manager.close()
