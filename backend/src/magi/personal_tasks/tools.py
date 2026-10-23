"""Host-owned personal task tools; execution plans remain run-owned."""

from __future__ import annotations

from typing import Any, Literal
import hashlib

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from magi_plugin_sdk.tools import (
    ParameterType,
    Tool,
    ToolParameter,
    ToolResult,
    ToolSchema,
)

from .models import TaskConflictError, TaskMutation, TaskNotFoundError, TaskReference
from .service import get_personal_task_service
from ..core.tool_context import ToolExecutionContext


class TaskQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: str | None = Field(default=None, max_length=128)
    view: Literal[
        "all",
        "next",
        "projects",
        "review",
        "inbox",
        "active",
        "waiting",
        "someday",
        "completed",
        "cancelled",
    ] = "all"
    search: str = Field(default="", max_length=500)
    parent_id: str | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    history_offset: int = Field(default=0, ge=0)


class PersonalTaskQueryTool(Tool):
    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="personal_task_query",
            category="system",
            effect_replay_policy="read_only",
            timeout=10,
            description=(
                "Read the user's durable personal to-dos, projects, progress and context across conversations. "
                "Always query this source for current commitments; memory and old messages may be stale. "
                "Use item_id for the complete Markdown body, project actions and change history. "
                "Use view=next for currently actionable work, projects for projects, review for open items. "
                "Lists are exact database queries with pagination; follow next_offset when asked for all items. "
                "These are personal commitments, separate from task_query background runs and todo_write run plans."
            ),
            parameters=[
                ToolParameter(
                    name="item_id",
                    type=ParameterType.STRING,
                    required=False,
                    description="Exact ID for full detail.",
                ),
                ToolParameter(
                    name="view",
                    type=ParameterType.STRING,
                    required=False,
                    default="all",
                    enum=[
                        "all",
                        "next",
                        "projects",
                        "review",
                        "inbox",
                        "active",
                        "waiting",
                        "someday",
                        "completed",
                        "cancelled",
                    ],
                    description="List filter.",
                ),
                ToolParameter(
                    name="search",
                    type=ParameterType.STRING,
                    required=False,
                    description="Literal text in title or body; try shorter terms if no match.",
                ),
                ToolParameter(
                    name="parent_id",
                    type=ParameterType.STRING,
                    required=False,
                    description="List actions belonging to this project.",
                ),
                ToolParameter(
                    name="limit",
                    type=ParameterType.INTEGER,
                    required=False,
                    description="Page size, 1 to 100.",
                ),
                ToolParameter(
                    name="offset",
                    type=ParameterType.INTEGER,
                    required=False,
                    description="List page offset.",
                ),
                ToolParameter(
                    name="history_offset",
                    type=ParameterType.INTEGER,
                    required=False,
                    description="History page offset for full detail.",
                ),
            ],
            tags=["personal", "todo", "gtd", "projects", "progress"],
        )

    async def execute(
        self, parameters: dict[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        try:
            query = TaskQuery.model_validate(parameters)
            user_id = context.env_vars.get("user_id", "").strip()
            if not user_id:
                raise ValueError("Personal task queries require an active user")
            store = get_personal_task_service().store
            if query.item_id:
                result = await store.get(
                    user_id, query.item_id, history_offset=query.history_offset
                )
            else:
                result = await store.query(
                    user_id, **query.model_dump(exclude={"item_id", "history_offset"})
                )
            data = result.model_dump(mode="json")
            if not query.item_id:
                # Discovery stays bounded; full context is read explicitly by item ID.
                for item in data["items"]:
                    body = item.pop("body_md")
                    item["body_preview"] = body[:240]
                    item["body_truncated"] = len(body) > 240
            return ToolResult(success=True, data=data)
        except TaskNotFoundError as exc:
            return ToolResult(success=False, error=str(exc), error_code="PERSONAL_TASK_NOT_FOUND")
        except (ValueError, RuntimeError) as exc:
            return ToolResult(
                success=False, error=str(exc), error_code="PERSONAL_TASK_QUERY_FAILED"
            )


class PersonalTaskUpdateTool(Tool):
    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="personal_task_update",
            category="system",
            effect_class="external_write",
            effect_replay_policy="reconcilable",
            timeout=15,
            description=(
                "Persist personal to-dos and progress explicitly communicated by the current user. "
                "Capture clear first-person commitments and direct requests to remember a task; do not require magic wording. "
                "Do not create commitments from assistant suggestions, quotations, hypothetical wishes, imported archives, "
                "or third-party observations. When the user asks to save an undecided idea, use inbox or someday. "
                "Read existing items first to avoid duplicates and preserve their background. "
                "For updates use the latest item_id and expected_version; fields are partial patches. "
                "The body_md retains goals, constraints, decisions and source context; project actions are separate records. "
                "Record work products and progress using action=progress and note; only complete human work when the user says it is done. "
                "This tool only stores the text supplied; it does not produce drafts or artifacts. "
                "When saving a short text draft, note must contain the complete usable draft, not a statement that it exists. "
                "For file outputs, preserve a usable artifact reference and summary. "
                "Every progress command MUST include fields.status for the resulting state (preserve the current status if unchanged). "
                "Waiting on another person is status=waiting, never just a sentence in body_md. "
                "Keep current status and dates in structured fields, not duplicated as Markdown status sections. "
                "Do not mark a project complete merely because an assistant produced a draft. "
                "Delete only when the user requests deletion; cascade=true explicitly deletes the project's actions too. "
                "Never invent deadlines. due/defer_until accept ISO dates or offset timestamps. "
                "Day-only requests must stay YYYY-MM-DD without invented midnight or end-of-day times. "
                "remind_at requires an offset timestamp and an explicit reminder request. timezone is an IANA timezone. "
                "Confirm success only after this tool succeeds. Reuse request_id for a retry of the same logical change."
            ),
            parameters=[
                ToolParameter(
                    name="request_id",
                    type=ParameterType.STRING,
                    required=True,
                    description="Stable operation key within this turn, such as create-1; reuse only for the identical command.",
                ),
                ToolParameter(
                    name="action",
                    type=ParameterType.STRING,
                    required=True,
                    enum=["create", "update", "progress", "delete"],
                    description="Mutation kind.",
                ),
                ToolParameter(
                    name="item_id",
                    type=ParameterType.STRING,
                    required=False,
                    description="Existing personal item ID; omit for create.",
                ),
                ToolParameter(
                    name="expected_version",
                    type=ParameterType.INTEGER,
                    required=False,
                    description="Zero for create; latest version for all other actions.",
                ),
                ToolParameter(
                    name="fields",
                    type=ParameterType.OBJECT,
                    required=False,
                    description=(
                        "Partial fields: title, body_md, kind(action|project), parent_id, status(inbox|active|waiting|someday|completed|cancelled), "
                        "due, defer_until, remind_at, timezone, references([{kind:chat|memory|resource|run|source,id,label,session_id}]). "
                        "Use null to clear optional time or parent fields; never send null for title/body/status/kind/timezone."
                    ),
                ),
                ToolParameter(
                    name="note",
                    type=ParameterType.STRING,
                    required=False,
                    description="Progress or reason for the change. Required for progress.",
                ),
                ToolParameter(
                    name="cascade",
                    type=ParameterType.BOOLEAN,
                    required=False,
                    description="Delete project actions as well, only if requested.",
                ),
            ],
            tags=["personal", "todo", "gtd", "projects", "progress"],
        )

    async def execute(
        self, parameters: dict[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        try:
            command = TaskMutation.model_validate(parameters)
            user_id = context.env_vars.get("user_id", "").strip()
            turn_id = context.env_vars.get("turn_id", "").strip()
            session_id = context.env_vars.get("session_id", "").strip()
            if not user_id or not turn_id or not session_id:
                raise ValueError("Personal task changes require a user conversation and turn")
            needs_timezone = (
                any((command.fields.due, command.fields.defer_until, command.fields.remind_at))
                and command.fields.timezone is None
            )
            if needs_timezone and command.item_id:
                existing = (
                    await get_personal_task_service().store.get(user_id, command.item_id)
                ).item
                # Existing calendar dates retain their original interpretation.
                # An undated capture has not established a user timezone yet.
                if any((existing.due, existing.defer_until, existing.remind_at)):
                    command.fields.timezone = existing.timezone
                    needs_timezone = False
            if needs_timezone:
                port = context.capabilities.environment if context.capabilities else None
                client = (
                    await port.read_client(user_id=user_id, session_id=session_id, turn_id=turn_id)
                    if port
                    else {}
                )
                if client.get("status") != "available" or not isinstance(
                    client.get("timezone"), str
                ):
                    raise ValueError(
                        "Dated tasks require a verified timezone; use current_time to resolve relative dates and supply timezone"
                    )
                command.fields.timezone = client["timezone"]
            operation_key = f"{turn_id}:{command.request_id}"
            command.request_id = "turn:" + hashlib.sha256(operation_key.encode()).hexdigest()
            result = await get_personal_task_service().mutate(
                user_id,
                command,
                actor="agent",
                references=[TaskReference(kind="chat", id=turn_id, session_id=session_id)],
            )
            return ToolResult(success=True, data=result.model_dump(mode="json"))
        except TaskConflictError as exc:
            return ToolResult(success=False, error=str(exc), error_code="PERSONAL_TASK_CONFLICT")
        except TaskNotFoundError as exc:
            return ToolResult(success=False, error=str(exc), error_code="PERSONAL_TASK_NOT_FOUND")
        except (ValidationError, ValueError, RuntimeError) as exc:
            return ToolResult(
                success=False, error=str(exc), error_code="PERSONAL_TASK_UPDATE_FAILED"
            )
