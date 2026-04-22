"""``ask_user_question`` — suspend the loop until the user replies.

The tool opens an :class:`AskState` in the control session store,
then awaits the matching answer on the shared
:class:`InteractionBroker`. A background / subagent caller is refused
unless the call site explicitly marked the invocation as interactive
via ``ToolExecutionContext.enabled_features`` — background tasks
cannot block on a human prompt by default.
"""

from __future__ import annotations

from typing import Any, Dict

from ...core.logger import get_logger
from ...core.runtime_bindings import (
    require_control_interaction_broker,
    require_control_session_store,
)
from ...agent.control.common import InteractionTimeoutError
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
                "Ask the user a clarifying question and wait for their "
                "reply. Use sparingly — only when proceeding without "
                "the answer would cause rework. Provide optional "
                "multiple-choice ``options``; the user can still "
                "answer freely unless ``allow_free_text`` is false. "
                "The call returns the user's reply as a string."
            ),
            category="control",
            parameters=[
                ToolParameter(
                    name="question",
                    type=ParameterType.STRING,
                    description="The question to ask the user.",
                    required=True,
                ),
                ToolParameter(
                    name="options",
                    type=ParameterType.ARRAY,
                    array_item_type=ParameterType.STRING,
                    description="Optional list of suggested answers.",
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
                    description=(
                        "Max seconds to wait for an answer. Defaults to 300."
                    ),
                    required=False,
                    default=_DEFAULT_TIMEOUT_SECONDS,
                    min_value=1,
                    max_value=3600,
                ),
            ],
            tags=["control", "ask"],
            timeout=600,
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

        intent = str(context.env_vars.get("intent") or "").strip()
        turn_id = str(context.env_vars.get("turn_id") or "").strip() or None
        # Background and scheduled tasks don't have a human waiting on
        # the UI; refuse unless the call site opts in via a feature
        # flag (``allow_ask_in_background``).
        if intent.startswith("background") and (
            "allow_ask_in_background" not in set(context.enabled_features or [])
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
        options: list[str] = [
            str(o).strip() for o in options_raw if str(o).strip()
        ] if isinstance(options_raw, list) else []
        allow_free_text = bool(parameters.get("allow_free_text", True))
        try:
            timeout_seconds = float(
                parameters.get("timeout_seconds", _DEFAULT_TIMEOUT_SECONDS)
            )
        except (TypeError, ValueError):
            timeout_seconds = _DEFAULT_TIMEOUT_SECONDS
        timeout_seconds = max(1.0, min(timeout_seconds, 3600.0))

        try:
            store = require_control_session_store()
            broker = require_control_interaction_broker()
        except RuntimeError as exc:
            return ToolResult(success=False, error=str(exc))

        ask = await store.open_ask(
            sid,
            question=question,
            options=options,
            allow_free_text=allow_free_text,
        )
        is_background = intent.startswith("background")
        logger.info(
            "ask_user_question.opened",
            session_id=sid,
            request_id=ask.request_id,
            background=is_background,
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

        try:
            answer = await broker.wait(
                interaction_id=ask.request_id,
                kind="ask",
                timeout_seconds=timeout_seconds,
            )
        except InteractionTimeoutError:
            await store.close_ask(sid, answer=None, resolution="timeout")
            return ToolResult(
                success=False,
                error=f"no answer within {timeout_seconds:.0f}s",
            )

        answer_text = str(answer) if answer is not None else ""
        await store.close_ask(sid, answer=answer_text, resolution="user")
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
                logger.debug(
                    "ask_user_question.resume_event_failed", exc_info=True
                )
        return ToolResult(success=True, data={"answer": answer_text})


__all__ = ["AskUserQuestionTool"]
