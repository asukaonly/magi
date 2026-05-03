"""REST API for user-invocable command execution from the `/`-picker.

`POST /api/commands/run` runs a tool by name with arbitrary arguments and
records the call as a (command_invocation, command_result) pair in the
chat timeline. Permission gating reuses the existing PermissionGateway so
dangerous tools still go through brokered_prompter.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...agent.control.permission.provider import get_permission_gateway
from ...commands import CommandRunner
from ...core.logger import get_logger
from ...runtime_defaults import DEFAULT_USER_ID
from ...tools import tool_registry

logger = get_logger(__name__)


commands_router = APIRouter()


class RunCommandRequest(BaseModel):
    user_id: str = Field(default=DEFAULT_USER_ID)
    session_id: str = Field(..., min_length=1)
    tool_name: str = Field(..., min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    invocation_text: str = Field(default="", description="Original /text typed by the user")
    workspace_path: str | None = None


class ListCommandsResponse(BaseModel):
    data: list[dict[str, Any]]


@commands_router.get("/", response_model=ListCommandsResponse)
async def list_user_invocable_commands() -> ListCommandsResponse:
    from ...commands import get_default_resolver

    resolver = get_default_resolver()
    out: list[dict[str, Any]] = []
    for name in resolver.list_user_invocable(tool_registry):
        info = tool_registry.get_tool_info(name) or {}
        out.append({
            "name": name,
            "description": info.get("description", ""),
            "category": info.get("category", ""),
            "dangerous": bool(info.get("dangerous", False)),
            "parameters": info.get("parameters", []),
        })
    return ListCommandsResponse(data=out)


@commands_router.post("/run")
async def run_command(request: RunCommandRequest) -> dict[str, Any]:
    runner = _build_runner()
    try:
        result = await runner.run_tool_command(
            user_id=request.user_id,
            session_id=request.session_id,
            tool_name=request.tool_name,
            arguments=dict(request.arguments or {}),
            invocation_text=request.invocation_text,
            agent_id=request.user_id,
            workspace=request.workspace_path,
        )
    except Exception as exc:
        logger.exception("Command run failed: %s", request.tool_name)
        raise HTTPException(status_code=500, detail=str(exc))
    return {
        "success": result.success,
        "message_id": result.message_id,
        "invocation_message_id": result.invocation_message_id,
        "output": result.output_text,
        "error": result.error,
        "error_code": result.error_code,
        "execution_time_ms": result.execution_time_ms,
    }


def _build_runner() -> CommandRunner:
    notifier = _resolve_notifier()
    return CommandRunner(
        registry=tool_registry,
        permission_gateway_provider=_safe_gateway_provider,
        notifier=notifier,
    )


def _safe_gateway_provider() -> Any | None:
    try:
        return get_permission_gateway()
    except RuntimeError:
        return None


def _resolve_notifier():
    """Return a notifier callable that emits chat-message-upsert events.

    Returns ``None`` if the runtime trace store is not initialized — tests
    and bootstrap edge cases work without it.
    """
    try:
        from ...agent.task_agents.chat.postprocess.notifications import (
            ChatRuntimeNotifier,
        )
    except Exception:
        return None
    try:
        from ...chat import get_chat_read_service
        from ...core.container import get_container

        container = get_container()
        store_provider = container.runtime_trace_store
        store = store_provider() if store_provider is not None else None
        if store is None or type(store).__name__ == "object":
            return None
        notifier = ChatRuntimeNotifier(
            runtime_trace_store=store,
            chat_read_service_factory=get_chat_read_service,
        )
    except Exception:
        return None

    async def _emit(user_id: str, session_id: str, message_id: str) -> None:
        await notifier.emit_chat_message_upsert(
            user_id=user_id,
            session_id=session_id,
            message_id=message_id,
        )

    return _emit
