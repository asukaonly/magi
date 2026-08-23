"""REST API for user-invocable command execution from the `/`-picker.

`POST /api/commands/run` runs a tool by name with arbitrary arguments and
records the call as a (command_invocation, command_result) pair in the
chat timeline. Permission gating reuses the existing PermissionGateway so
dangerous tools still go through brokered_prompter.

`GET /api/commands/skills` lists user-invocable skills and
`POST /api/commands/expand-skill` renders one — the rendered text is then
sent as a normal chat message via the existing dispatch path. Skills are
distinct from tools: a skill expansion *becomes the user's next turn*
rather than producing a tool_result row.

`POST /api/commands/run-skill-as-background` renders a skill and enqueues
it as a BackgroundTask so the sub-agent runs out of band and the user's
main chat session stays free. Used for skills marked ``context: fork``.
The completion is delivered back into the originating session's chat
transcript by the outreach completion producer (see :mod:`magi.outreach`)
as a ``background_task_completion`` chat message.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ... import i18n as core_i18n
from ...agent.background.contracts import (
    BackgroundTaskSpec,
    BackgroundTaskTriggerSource,
)
from ...agent.background.provider import resolve_background_task_manager
from ...control.permission.provider import get_permission_gateway
from ...commands import CommandRunner
from ...core.logger import get_logger
from ...core.runtime_bindings import require_chat_surface_write_service
from ...identity import CANONICAL_LOCAL_USER as DEFAULT_USER_ID
from ...skills.expander import SkillExpansion, expand_skill
from ...skills.provider import resolve_skill_indexer
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
        out.append(
            {
                "name": name,
                "description": info.get("description", ""),
                "category": info.get("category", ""),
                "dangerous": bool(info.get("dangerous", False)),
                "parameters": info.get("parameters", []),
            }
        )
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
    return CommandRunner(
        registry=tool_registry,
        permission_gateway_provider=_safe_gateway_provider,
        transcript_writer=require_chat_surface_write_service(),
    )


def _safe_gateway_provider() -> Any | None:
    try:
        return get_permission_gateway()
    except RuntimeError:
        return None


# ---------------------------------------------------------------------------
# Skills (user-invocable, prompt-style)
# ---------------------------------------------------------------------------


class SkillDescriptor(BaseModel):
    name: str
    description: str
    argument_hint: str | None = None
    category: str | None = None
    tags: list[str] = []
    context_mode: str | None = None  # "fork" | None


class ListSkillsResponse(BaseModel):
    data: list[SkillDescriptor]


@commands_router.get("/skills", response_model=ListSkillsResponse)
async def list_user_invocable_skills() -> ListSkillsResponse:
    try:
        indexer = resolve_skill_indexer()
    except RuntimeError:
        return ListSkillsResponse(data=[])
    out: list[SkillDescriptor] = []
    for name in indexer.get_skill_names():
        meta = indexer.get_metadata(name)
        if meta is None or not meta.user_invocable:
            continue
        out.append(
            SkillDescriptor(
                name=meta.name,
                description=meta.description or "",
                argument_hint=meta.argument_hint,
                category=meta.category,
                tags=list(meta.tags or []),
                context_mode=meta.context,
            )
        )
    out.sort(key=lambda s: s.name)
    return ListSkillsResponse(data=out)


class ExpandSkillRequest(BaseModel):
    user_id: str = Field(default=DEFAULT_USER_ID)
    session_id: str = Field(default="")
    skill_name: str = Field(..., min_length=1)
    arguments: list[str] = Field(default_factory=list)
    workspace_path: str | None = None


class ExpandSkillResponse(BaseModel):
    name: str
    rendered_prompt: str
    invocation_text: str
    description: str
    argument_hint: str | None = None
    allowed_tools: list[str] | None = None
    context_mode: str | None = None


@commands_router.post("/expand-skill", response_model=ExpandSkillResponse)
async def expand_skill_endpoint(request: ExpandSkillRequest) -> ExpandSkillResponse:
    try:
        expansion = expand_skill(
            skill_name=request.skill_name,
            arguments=request.arguments,
            user_id=request.user_id,
            session_id=request.session_id,
            workspace=request.workspace_path,
        )
    except RuntimeError as exc:
        # Skill loader binding not initialized yet.
        raise HTTPException(status_code=503, detail=str(exc))
    if expansion is None:
        raise HTTPException(
            status_code=404,
            detail=core_i18n.t(
                "commands.skills.not_found",
                fallback="Skill {skill_name!r} not found",
                skill_name=request.skill_name,
            ),
        )
    if not expansion.user_invocable:
        raise HTTPException(
            status_code=403,
            detail=core_i18n.t(
                "commands.skills.not_user_invocable",
                fallback="Skill {skill_name!r} is not user-invocable",
                skill_name=request.skill_name,
            ),
        )
    return ExpandSkillResponse(
        name=expansion.name,
        rendered_prompt=expansion.rendered_prompt,
        invocation_text=expansion.invocation_text,
        description=expansion.description,
        argument_hint=expansion.argument_hint,
        allowed_tools=expansion.allowed_tools,
        context_mode=expansion.context_mode,
    )


# ---------------------------------------------------------------------------
# Run a skill as a background task (context: fork)
# ---------------------------------------------------------------------------


class RunSkillAsBackgroundRequest(BaseModel):
    user_id: str = Field(default=DEFAULT_USER_ID)
    session_id: str = Field(..., min_length=1)
    skill_name: str = Field(..., min_length=1)
    arguments: list[str] = Field(default_factory=list)
    workspace_path: str | None = None
    origin_turn_id: str | None = None
    timeout_seconds: int | None = 1800
    max_iterations: int = 50


class RunSkillAsBackgroundResponse(BaseModel):
    task_id: str
    title: str
    invocation_text: str
    selected_tools: list[str]
    pending_message_id: str


def _expand_background_skill(request: RunSkillAsBackgroundRequest) -> SkillExpansion:
    try:
        expansion = expand_skill(
            skill_name=request.skill_name,
            arguments=request.arguments,
            user_id=request.user_id,
            session_id=request.session_id,
            workspace=request.workspace_path,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if expansion is None:
        raise HTTPException(
            status_code=404,
            detail=core_i18n.t(
                "commands.skills.not_found",
                fallback="Skill {skill_name!r} not found",
                skill_name=request.skill_name,
            ),
        )
    _ensure_background_skill(expansion, request.skill_name)
    return expansion


def _ensure_background_skill(expansion: SkillExpansion, skill_name: str) -> None:
    if not expansion.user_invocable:
        raise HTTPException(
            status_code=403,
            detail=core_i18n.t(
                "commands.skills.not_user_invocable",
                fallback="Skill {skill_name!r} is not user-invocable",
                skill_name=skill_name,
            ),
        )
    if expansion.context_mode != "fork":
        raise HTTPException(
            status_code=400,
            detail=core_i18n.t(
                "commands.skills.not_fork_context",
                fallback=(
                    "Skill {skill_name!r} is not declared context: fork."
                    " Use /expand-skill for inline skills."
                ),
                skill_name=skill_name,
            ),
        )


def _resolve_background_manager() -> Any:
    try:
        return resolve_background_task_manager()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _background_skill_title(expansion: SkillExpansion, skill_name: str) -> str:
    return expansion.invocation_text or f"/{skill_name}"


async def _create_background_skill_pending_message(
    *,
    writer: Any,
    request: RunSkillAsBackgroundRequest,
    expansion: SkillExpansion,
    title: str,
) -> str:
    return await writer.create_background_task_pending_message(
        user_id=request.user_id,
        session_id=request.session_id,
        title=title,
        trigger_source=BackgroundTaskTriggerSource.MANUAL.value,
        skill_name=expansion.name,
        invocation_text=expansion.invocation_text,
    )


def _background_skill_spec(
    *,
    request: RunSkillAsBackgroundRequest,
    expansion: SkillExpansion,
    title: str,
    selected_tools: list[str],
    pending_message_id: str,
) -> BackgroundTaskSpec:
    return BackgroundTaskSpec(
        user_id=request.user_id,
        session_id=request.session_id,
        origin_turn_id=str(request.origin_turn_id or ""),
        title=title,
        goal=expansion.rendered_prompt,
        selected_tools=selected_tools,
        workspace_path=request.workspace_path,
        trigger_source=BackgroundTaskTriggerSource.MANUAL,
        max_iterations=int(request.max_iterations),
        timeout_seconds=request.timeout_seconds,
        task_budget_root_turn_id=(
            str(request.origin_turn_id).strip() if request.origin_turn_id else None
        ),
        pending_message_id=pending_message_id,
    )


async def _attach_background_task_id(
    *,
    writer: Any,
    request: RunSkillAsBackgroundRequest,
    pending_message_id: str,
    task_id: str,
) -> None:
    await writer.attach_background_task_id(
        user_id=request.user_id,
        session_id=request.session_id,
        message_id=pending_message_id,
        task_id=task_id,
    )


def _background_skill_response(
    *,
    task_id: str,
    title: str,
    expansion: SkillExpansion,
    selected_tools: list[str],
    pending_message_id: str,
) -> RunSkillAsBackgroundResponse:
    return RunSkillAsBackgroundResponse(
        task_id=task_id,
        title=title,
        invocation_text=expansion.invocation_text,
        selected_tools=selected_tools,
        pending_message_id=pending_message_id,
    )


@commands_router.post(
    "/run-skill-as-background",
    response_model=RunSkillAsBackgroundResponse,
)
async def run_skill_as_background(
    request: RunSkillAsBackgroundRequest,
) -> RunSkillAsBackgroundResponse:
    """Render a fork-context skill and enqueue it as a background task.

    Validation matches ``expand-skill``: 404 if the skill is missing,
    403 if it's not user-invocable, 400 if the skill is not declared
    ``context: fork`` (the caller should use ``expand-skill`` for inline
    skills instead).
    """
    expansion = _expand_background_skill(request)
    manager = _resolve_background_manager()
    title = _background_skill_title(expansion, request.skill_name)
    selected_tools = list(expansion.allowed_tools or [])

    writer = require_chat_surface_write_service()
    pending_message_id = await _create_background_skill_pending_message(
        writer=writer,
        request=request,
        expansion=expansion,
        title=title,
    )

    spec = _background_skill_spec(
        request=request,
        expansion=expansion,
        title=title,
        selected_tools=selected_tools,
        pending_message_id=pending_message_id,
    )
    task = await manager.enqueue(spec)

    await _attach_background_task_id(
        writer=writer,
        request=request,
        pending_message_id=pending_message_id,
        task_id=task.task_id,
    )
    return _background_skill_response(
        task_id=task.task_id,
        title=title,
        expansion=expansion,
        selected_tools=selected_tools,
        pending_message_id=pending_message_id,
    )
