from __future__ import annotations

import os
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from magi.chat.runtime_forgetting import ChatRuntimeForgettingCoordinator
from magi.tools.builtin.bash_tool import BashTool
from magi.tools.lifecycle import clear_session_shell_jobs
from magi.tools.registry import ToolRegistry
from magi.tools.schema import ToolExecutionContext


@pytest.mark.asyncio
@pytest.mark.skipif(os.name == "nt", reason="POSIX shell integration")
@pytest.mark.parametrize("operation", ["prepare_session_delete", "quiesce_history_clear"])
async def test_forgetting_stops_completed_turn_jobs_only_in_target_session(
    tmp_path, monkeypatch, operation: str,
) -> None:
    monkeypatch.setenv("MAGI_CHILD_PROCESS_REGISTRY", str(tmp_path / "children.json"))
    registry = ToolRegistry()
    registry.register(BashTool)
    monkeypatch.setattr("magi.tools.tool_registry", registry)
    shell = registry.get_tool("bash")

    @asynccontextmanager
    async def boundary():
        yield

    async def purge(**kwargs):
        return 0

    coordinator = ChatRuntimeForgettingCoordinator(
        runtime_command_queue=SimpleNamespace(
            user_message_clear_boundary=boundary, block_user_message_scope_and_purge=purge,
        ),
        task_agent_manager=None, source_hub=None, chat_read_service=None, delivery_scheduler=None,
        clear_shell_jobs=clear_session_shell_jobs,
    )
    target_context = ToolExecutionContext(
        agent_id="child:finished", workspace=str(tmp_path),
        env_vars={"user_id": "user", "session_id": "deleted"},
    )
    other_context = target_context.model_copy(update={
        "env_vars": {"user_id": "user", "session_id": "other"},
    })
    try:
        target = await shell.execute({"command": "sleep 30", "background": True}, target_context)
        other = await shell.execute({"command": "sleep 30", "background": True}, other_context)
        target_job = shell.jobs._jobs[target.data["job_id"]]
        other_job = shell.jobs._jobs[other.data["job_id"]]

        await getattr(coordinator, operation)(user_id="user", session_id="deleted")

        assert target_job.task.done() and target_job.status == "cancelled"
        assert target_job.job_id not in shell.jobs._jobs
        assert not other_job.task.done() and other_job.status == "running"
        assert other_job.job_id in shell.jobs._jobs
    finally:
        await shell.clear_user_content()
