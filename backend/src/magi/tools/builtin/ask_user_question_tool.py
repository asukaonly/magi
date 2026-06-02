"""``ask_user_question`` — suspend the loop until the user replies.

The tool is a thin shell over the SDK ``InteractionPort`` ask-user
capability (``ctx.capabilities.interaction``). It validates the request,
delegates the entire control-protocol orchestration (opening the ask,
emitting transcript/UI events, suspending on the interaction broker, and
resolving on answer / cancel / timeout) to the host adapter, then maps the
returned :class:`AskOutcome` onto a :class:`ToolResult`.

A background / subagent caller is refused unless either the user preference
``allow_ask_in_background`` is on or the call site explicitly marked the
invocation as interactive via ``ToolExecutionContext.enabled_features`` —
background tasks cannot block on a human prompt by default.
"""

from __future__ import annotations

from typing import Any, Dict

from ...core.logger import get_logger

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

        interaction = (
            context.capabilities.interaction
            if context.capabilities is not None
            else None
        )
        if interaction is None:
            return ToolResult(
                success=False,
                error="ask_user_question requires the interaction capability",
            )

        cancellation = getattr(context, "cancellation", None)
        if cancellation is not None and await cancellation.is_cancelled():
            return ToolResult(
                success=False,
                error="run cancelled before answer",
                error_code="CANCELLED",
            )

        is_background = intent.startswith("background")
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
        background_port = (
            context.capabilities.background
            if context.capabilities is not None
            else None
        )

        try:
            outcome = await interaction.ask(
                session_id=sid,
                user_id=user_id,
                turn_id=turn_id,
                question=question,
                options=options,
                allow_free_text=allow_free_text,
                timeout_seconds=timeout_seconds,
                background=is_background,
                background_task_id=bg_task_id,
                background_port=background_port,
                cancellation=cancellation,
            )
        except RuntimeError as exc:
            return ToolResult(success=False, error=str(exc))

        if outcome.resolution == "cancelled":
            return ToolResult(
                success=False,
                error="run cancelled before answer",
                error_code="CANCELLED",
            )
        if outcome.timed_out:
            return ToolResult(
                success=False,
                error=f"no answer within {timeout_seconds:.0f}s",
            )
        return ToolResult(success=True, data={"answer": outcome.answer or ""})


__all__ = ["AskUserQuestionTool"]
