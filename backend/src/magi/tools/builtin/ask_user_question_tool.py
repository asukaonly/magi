"""``ask_user_question`` — suspend the loop until the user replies.

The tool opens an :class:`AskState` in the control session store,
then awaits the matching answer on the shared
:class:`InteractionBroker`. A background / subagent caller is refused
unless either the user preference ``allow_ask_in_background`` is on
or the call site explicitly marked the invocation as interactive via
``ToolExecutionContext.enabled_features`` — background tasks cannot
block on a human prompt by default.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import suppress
from typing import Any, Dict

from ...agent.control.provider import (
    resolve_control_interaction_broker,
    resolve_control_session_store,
)
from ...agent.control.common.events import (
    publish_control_ask_answered,
    publish_control_ask_requested,
)
from ...core.logger import get_logger
from ...agent.control.common import InteractionTimeoutError

_BACKGROUND_AGENT_PREFIX = "background:"
from ..schema import (
    ParameterType,
    Tool,
    ToolExecutionContext,
    ToolParameter,
    ToolResult,
    ToolSchema,
)

logger = get_logger(__name__)


_DEFAULT_TIMEOUT_SECONDS: float = 300.0


class AskUserQuestionTool(Tool):
    """Ask the user a single question and wait for the answer."""

    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="ask_user_question",
            description=(
                "Ask the user a clarifying question in the same "
                "language as the latest user message and wait for "
                "their reply. Use sparingly — only when proceeding "
                "without the answer would cause rework. Provide "
                "optional multiple-choice ``options``; the user can "
                "still answer freely unless ``allow_free_text`` is "
                "false. The call returns the user's reply as a string."
            ),
            category="control",
            parameters=[
                ToolParameter(
                    name="question",
                    type=ParameterType.STRING,
                    description=(
                        "The question to ask the user. Write it in the "
                        "same language as the latest user message."
                    ),
                    required=True,
                ),
                ToolParameter(
                    name="options",
                    type=ParameterType.ARRAY,
                    array_item_type=ParameterType.STRING,
                    description=(
                        "Optional list of suggested answers. Keep them "
                        "in the same language as the question unless the "
                        "user explicitly requested otherwise."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="allow_free_text",
                    type=ParameterType.BOOLEAN,
                    description=(
                        "Whether the user may type a freeform reply "
                        "instead of picking an option. Defaults to true."
                    ),
                    required=False,
                    default=True,
                ),
                ToolParameter(
                    name="timeout_seconds",
                    type=ParameterType.FLOAT,
                    description=("Max seconds to wait for an answer. Defaults to 300."),
                    required=False,
                    default=_DEFAULT_TIMEOUT_SECONDS,
                    min_value=1,
                    max_value=3600,
                ),
            ],
            tags=["control", "ask"],
            timeout=600,
            metadata={
                "task_intents": ["clarify_requirement"],
                "domains": ["user"],
                "operations": ["clarify"],
                "query_shapes": ["blocking_decision", "missing_preference"],
                "followed_by": [],
                "avoid_task_intents": [
                    "explore_codebase",
                    "trace_implementation",
                    "verify_source_claim",
                    "research_external",
                    "debug_runtime",
                    "apply_change",
                    "recall_context",
                ],
                "blocks_on_user": True,
                "cost": "high",
                "tool_hint": (
                    "Use only when a missing user decision blocks safe "
                    "progress or would likely cause rework. Write the "
                    "question and options in the same language as the "
                    "latest user message."
                ),
            },
        )

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        sid = str(context.env_vars.get("session_id") or "").strip()
        if not sid:
            return ToolResult(
                success=False,
                error="ask_user_question requires an active session",
            )

        user_id = str(context.env_vars.get("user_id") or "").strip() or None
        intent = str(context.env_vars.get("intent") or "").strip()
        turn_id = str(context.env_vars.get("turn_id") or "").strip() or None
        # Background and scheduled tasks don't have a human waiting on
        # the UI; refuse unless either the user preference
        # ``allow_ask_in_background`` is on or the call site opted in
        # via a ``allow_ask_in_background`` feature flag on the
        # execution context.
        pref_allow_ask = False
        try:
            from ...config import get_user_preference

            pref_allow_ask = bool(get_user_preference("allow_ask_in_background", False))
        except Exception:  # pragma: no cover - defensive
            pref_allow_ask = False
        if intent.startswith("background") and not (
            pref_allow_ask
            or "allow_ask_in_background" in set(context.enabled_features or [])
        ):
            return ToolResult(
                success=False,
                error=(
                    "ask_user_question is not allowed from background "
                    "context without the 'allow_ask_in_background' flag"
                ),
            )

        question = str(parameters.get("question") or "").strip()
        if not question:
            return ToolResult(
                success=False,
                error="ask_user_question requires a non-empty 'question'",
            )
        options_raw = parameters.get("options") or []
        options: list[str] = (
            [str(o).strip() for o in options_raw if str(o).strip()]
            if isinstance(options_raw, list)
            else []
        )
        allow_free_text = bool(parameters.get("allow_free_text", True))
        try:
            timeout_seconds = float(
                parameters.get("timeout_seconds", _DEFAULT_TIMEOUT_SECONDS)
            )
        except (TypeError, ValueError):
            timeout_seconds = _DEFAULT_TIMEOUT_SECONDS
        timeout_seconds = max(1.0, min(timeout_seconds, 3600.0))

        try:
            store = resolve_control_session_store()
            broker = resolve_control_interaction_broker()
        except RuntimeError as exc:
            return ToolResult(success=False, error=str(exc))

        cancellation = getattr(context, "cancellation", None)
        if cancellation is not None and await cancellation.is_cancelled():
            return ToolResult(
                success=False,
                error="run cancelled before answer",
                error_code="CANCELLED",
            )

        request_id = uuid.uuid4().hex
        answer_task = asyncio.create_task(
            broker.wait(
                interaction_id=request_id,
                kind="ask",
                timeout_seconds=timeout_seconds,
            ),
            name=f"ask-user-question-{request_id}",
        )
        cancel_task: asyncio.Task[None] | None = None
        if cancellation is not None:
            cancel_task = asyncio.create_task(
                cancellation.wait(),
                name=f"ask-user-question-cancel-{request_id}",
            )
        # Let the waiter enter the broker before the ask becomes externally visible.
        await asyncio.sleep(0)
        if cancellation is not None and await cancellation.is_cancelled():
            answer_task.cancel()
            if cancel_task is not None:
                cancel_task.cancel()
            with suppress(asyncio.CancelledError):
                await answer_task
            if cancel_task is not None:
                with suppress(asyncio.CancelledError):
                    await cancel_task
            return ToolResult(
                success=False,
                error="run cancelled before answer",
                error_code="CANCELLED",
            )

        try:
            ask = await store.open_ask(
                sid,
                question=question,
                options=options,
                allow_free_text=allow_free_text,
                timeout_seconds=timeout_seconds,
                request_id=request_id,
            )
        except Exception:
            answer_task.cancel()
            if cancel_task is not None:
                cancel_task.cancel()
            with suppress(asyncio.CancelledError):
                await answer_task
            if cancel_task is not None:
                with suppress(asyncio.CancelledError):
                    await cancel_task
            raise

        is_background = intent.startswith("background")
        try:
            await publish_control_ask_requested(
                session_id=sid,
                user_id=user_id,
                turn_id=turn_id,
                ask=ask,
                background=is_background,
            )
        except Exception:
            logger.debug("ask_user_question.persist_request_failed", exc_info=True)
        # Resolve the owning background task id from the execution
        # agent id when this call originates from BackgroundTaskManager
        # (``execute_with_tools`` sets ``execution_agent_id =
        # f"background:{task_id}"``). Falls back to ``None`` on any
        # shape mismatch so the tool still works outside a background
        # context.
        bg_task_id: str | None = None
        agent_id = str(getattr(context, "agent_id", "") or "")
        if is_background and agent_id.startswith(_BACKGROUND_AGENT_PREFIX):
            candidate = agent_id[len(_BACKGROUND_AGENT_PREFIX) :].strip()
            bg_task_id = candidate or None
        logger.info(
            "ask_user_question.opened",
            session_id=sid,
            request_id=ask.request_id,
            background=is_background,
            bg_task_id=bg_task_id,
        )
        if bg_task_id is not None:
            try:
                manager = (
                    context.capabilities.background
                    if context.capabilities is not None
                    else None
                )
                if manager is not None:
                    await manager.suspend_waiting_user(
                        bg_task_id, reason="awaiting_user_answer"
                    )
            except Exception:  # pragma: no cover - defensive
                logger.debug(
                    "ask_user_question.manager_suspend_failed",
                    exc_info=True,
                )
        try:
            from ...agent.control.common.events import publish_control_event

            await publish_control_event(
                "control.ask.requested",
                {
                    "request_id": ask.request_id,
                    "session_id": sid,
                    "question": question,
                    "options": list(options or []),
                    "allow_free_text": allow_free_text,
                    "timeout_seconds": timeout_seconds,
                    "created_at_ms": int(ask.asked_at * 1000),
                    "expires_at_ms": int(ask.expires_at * 1000) if ask.expires_at else None,
                    "background": is_background,
                },
                session_id=sid,
                turn_id=turn_id,
            )
            if is_background:
                await publish_control_event(
                    "control.background.suspended",
                    {
                        "session_id": sid,
                        "request_id": ask.request_id,
                        "reason": "awaiting_user_answer",
                        "timeout_seconds": timeout_seconds,
                    },
                    session_id=sid,
                    turn_id=turn_id,
                )
        except Exception:  # pragma: no cover - defensive
            logger.debug("ask_user_question.event_failed", exc_info=True)

        pending_tasks: set[asyncio.Task[Any]] = {answer_task}
        if cancel_task is not None:
            pending_tasks.add(cancel_task)

        try:
            done, pending = await asyncio.wait(
                pending_tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if (
                cancel_task is not None
                and cancel_task in done
                and await cancellation.is_cancelled()
            ):
                answer_task.cancel()
                with suppress(asyncio.CancelledError):
                    await answer_task
                closed_ask = await store.close_ask(sid, answer=None, resolution="cancelled")
                if closed_ask is not None:
                    try:
                        await publish_control_ask_requested(
                            session_id=sid,
                            user_id=user_id,
                            turn_id=turn_id,
                            ask=closed_ask,
                            background=is_background,
                        )
                    except Exception:
                        logger.debug("ask_user_question.persist_cancelled_failed", exc_info=True)
                if bg_task_id is not None:
                    try:
                        manager = (
                            context.capabilities.background
                            if context.capabilities is not None
                            else None
                        )
                        if manager is not None:
                            await manager.resume_from_wait(bg_task_id)
                    except Exception:  # pragma: no cover - defensive
                        logger.debug(
                            "ask_user_question.manager_resume_failed",
                            exc_info=True,
                        )
                logger.info(
                    "ask_user_question.cancelled",
                    session_id=sid,
                    request_id=ask.request_id,
                    reason=getattr(cancellation, "reason", None),
                )
                return ToolResult(
                    success=False,
                    error="run cancelled before answer",
                    error_code="CANCELLED",
                )
            for task in pending:
                task.cancel()
            for task in pending:
                with suppress(asyncio.CancelledError):
                    await task
            answer = await answer_task
        except InteractionTimeoutError:
            closed_ask = await store.close_ask(sid, answer=None, resolution="timeout")
            if closed_ask is not None:
                try:
                    await publish_control_ask_requested(
                        session_id=sid,
                        user_id=user_id,
                        turn_id=turn_id,
                        ask=closed_ask,
                        background=is_background,
                    )
                except Exception:
                    logger.debug("ask_user_question.persist_timeout_failed", exc_info=True)
            if bg_task_id is not None:
                try:
                    manager = (
                        context.capabilities.background
                        if context.capabilities is not None
                        else None
                    )
                    if manager is not None:
                        await manager.resume_from_wait(bg_task_id)
                except Exception:  # pragma: no cover - defensive
                    logger.debug(
                        "ask_user_question.manager_resume_failed",
                        exc_info=True,
                    )
            return ToolResult(
                success=False,
                error=f"no answer within {timeout_seconds:.0f}s",
            )

        answer_text = str(answer) if answer is not None else ""
        closed_ask = await store.close_ask(sid, answer=answer_text, resolution="user")
        if closed_ask is not None:
            try:
                await publish_control_ask_answered(
                    session_id=sid,
                    user_id=user_id,
                    turn_id=turn_id,
                    ask=closed_ask,
                    answer=answer_text,
                    background=is_background,
                )
            except Exception:
                logger.debug("ask_user_question.persist_response_failed", exc_info=True)
        if bg_task_id is not None:
            try:
                manager = (
                    context.capabilities.background
                    if context.capabilities is not None
                    else None
                )
                if manager is not None:
                    await manager.resume_from_wait(bg_task_id)
            except Exception:  # pragma: no cover - defensive
                logger.debug(
                    "ask_user_question.manager_resume_failed",
                    exc_info=True,
                )
        logger.info(
            "ask_user_question.answered",
            session_id=sid,
            request_id=ask.request_id,
            length=len(answer_text),
        )
        if is_background:
            try:
                from ...agent.control.common.events import publish_control_event

                await publish_control_event(
                    "control.background.resumed",
                    {
                        "session_id": sid,
                        "request_id": ask.request_id,
                    },
                    session_id=sid,
                    turn_id=turn_id,
                )
            except Exception:  # pragma: no cover - defensive
                logger.debug("ask_user_question.resume_event_failed", exc_info=True)
        return ToolResult(success=True, data={"answer": answer_text})


__all__ = ["AskUserQuestionTool"]
