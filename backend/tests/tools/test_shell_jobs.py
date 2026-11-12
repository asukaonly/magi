from __future__ import annotations

import asyncio
import os

import pytest

from magi.agent.execution.local_tool_rendering import render_local_result
from magi.control.cancel import EventCancelToken
from magi.tools.builtin.bash_tool import BashTool
from magi.tools.builtin.shell_job_tool import ShellJobTool
from magi.tools.registry import ToolRegistry
from magi.tools.schema import ToolExecutionContext

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(os.name == "nt", reason="POSIX shell integration")]


def _setup(tmp_path, monkeypatch):
    monkeypatch.setenv("MAGI_CHILD_PROCESS_REGISTRY", str(tmp_path / "children.json"))
    registry = ToolRegistry()
    registry.register(BashTool)
    registry.register(ShellJobTool)
    context = ToolExecutionContext(
        agent_id="chat:session", workspace=str(tmp_path),
        env_vars={"user_id": "user", "session_id": "session"},
    )
    return registry.get_tool("bash"), registry.get_tool("shell_job"), context


async def test_foreground_deadline_hands_off_live_output_and_terminal_exit(tmp_path, monkeypatch):
    shell, control, context = _setup(tmp_path, monkeypatch)
    try:
        started = await shell.execute({"command": "printf started; sleep 1.2; printf finished; exit 1", "timeout": 1}, context)
        assert started.success and started.data["status"] == "running"
        assert started.data["risk_level"] in {"read_only", "mutating"}
        assert started.data["stdout"] == "started"
        assert started.data["tool_expansion"]["append_tools"] == ["shell_job"]
        job_id = started.data["job_id"]
        text = render_local_result("bash", started.data, success=True, error_code=None,
                                   max_items=10, max_text_chars=1000, max_chars=4000)
        assert job_id in text and "Command running" in text and "shell_job" in text
        completed = await control.execute({"action": "wait", "job_id": job_id, "wait_seconds": 5}, context)
        assert completed.success and completed.data["status"] == "completed"
        assert completed.data["stdout"] == "startedfinished"
        assert completed.data["return_code"] == 1 and completed.data["command_succeeded"] is False
        text = render_local_result("shell_job", completed.data, success=True, error_code=None,
                                   max_items=10, max_text_chars=1000, max_chars=4000)
        assert "Command failed; exit code: 1" in text
    finally:
        await shell.clear_user_content()


async def test_background_service_is_owned_and_explicitly_stoppable(tmp_path, monkeypatch):
    shell, control, context = _setup(tmp_path, monkeypatch)
    try:
        started = await shell.execute({"command": "sleep 30", "background": True}, context)
        assert started.success and started.data["status"] == "running"
        job_id = started.data["job_id"]
        child = context.model_copy(update={"agent_id": "child:helper"})
        assert (await control.execute({"action": "poll", "job_id": job_id}, child)).success
        for update in ({"env_vars": {"user_id": "user", "session_id": "other"}},
                       {"env_vars": {"user_id": "other", "session_id": "session"}}):
            other = context.model_copy(update=update)
            denied = await control.execute({"action": "stop", "job_id": job_id}, other)
            assert not denied.success and denied.error_code == "NOT_FOUND"
            listed = await control.execute({"action": "list"}, other)
            assert listed.data["jobs"] == []
        stopped = await control.execute({"action": "stop", "job_id": job_id}, context)
        assert stopped.success and stopped.data["status"] == "cancelled"
        assert stopped.data["stopped"] and not stopped.data["command_succeeded"]
        again = await control.execute({"action": "stop", "job_id": job_id}, context)
        assert again.data["status"] == "cancelled"
    finally:
        await shell.clear_user_content()


async def test_cancellation_terminates_job_and_descendants(tmp_path, monkeypatch):
    shell, control, context = _setup(tmp_path, monkeypatch)
    token = EventCancelToken()
    context.cancellation = token
    try:
        started = await shell.execute({
            "command": "(touch ready; while [ ! -e release ]; do sleep 0.05; done; touch leaked) & wait",
            "background": True,
        }, context)
        job_id = started.data["job_id"]

        async def wait_for_child_ready() -> None:
            while not (tmp_path / "ready").exists():
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_for_child_ready(), timeout=10)
        token.cancel("user_cancelled")
        job = shell.jobs._jobs[job_id]
        await asyncio.wait_for(asyncio.shield(job.task), timeout=25)
        assert job.status == "cancelled"
        # Release only after cancellation has settled, regardless of machine load.
        (tmp_path / "release").touch()
        await asyncio.sleep(0.2)
        assert not (tmp_path / "leaked").exists()
    finally:
        await shell.clear_user_content()


async def test_user_content_clear_stops_live_jobs_and_erases_receipts(tmp_path, monkeypatch):
    shell, control, context = _setup(tmp_path, monkeypatch)
    started = await shell.execute({"command": "sleep 30", "background": True}, context)
    job = shell.jobs._jobs[started.data["job_id"]]
    await shell.clear_user_content()
    assert job.task.done() and job.status == "cancelled"
    assert (await control.execute({"action": "list"}, context)).data["jobs"] == []


async def test_spawn_failure_does_not_report_background_started(tmp_path, monkeypatch):
    shell, control, context = _setup(tmp_path, monkeypatch)
    result = await shell.execute({"command": "echo hi", "cwd": str(tmp_path / "missing"), "background": True}, context)
    assert not result.success and result.data["status"] == "failed"
    assert result.data["pid"] is None
    assert result.metadata["effect_state"] == "none"
    (tmp_path / "missing").mkdir()
    retried = await shell.execute({"command": "echo hi", "cwd": str(tmp_path / "missing")}, context)
    assert retried.success and retried.data["return_code"] == 0
    await shell.clear_user_content()
