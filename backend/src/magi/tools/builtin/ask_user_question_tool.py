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

from dataclasses import dataclass
from typing import Any, Dict

from ...core.logger import get_logger

from ..schema import (
    ParameterType,
    Tool,
    ToolExecutionContext,
    ToolParameter,
    ToolResult,
    ToolSchema,
)

_BACKGROUND_AGENT_PREFIX = "background:"

logger = get_logger(__name__)


_DEFAULT_TIMEOUT_SECONDS: float = 300.0


@dataclass(frozen=True)
class _AskRequest:
    session_id: str
    user_id: str | None
    turn_id: str | None
    intent: str
    question: str
    options: list[str]
    allow_free_text: bool
    timeout_seconds: float


def _env_text(context: ToolExecutionContext, key: str) -> str:
    return str(context.env_vars.get(key) or "").strip()


def _optional_env_text(context: ToolExecutionContext, key: str) -> str | None:
    value = _env_text(context, key)
    return value or None


def _background_ask_allowed(context: ToolExecutionContext) -> bool:
    pref_allow_ask = False
    try:
        from ...config import get_user_preference

        pref_allow_ask = bool(get_user_preference("allow_ask_in_background", False))
    except Exception:  # pragma: no cover - defensive
        pref_allow_ask = False
    return pref_allow_ask or "allow_ask_in_background" in set(context.enabled_features or [])


def _parse_question(parameters: Dict[str, Any]) -> str:
    return str(parameters.get("question") or "").strip()


def _parse_options(parameters: Dict[str, Any]) -> list[str]:
    options_raw = parameters.get("options") or []
    if not isinstance(options_raw, list):
        return []
    return [str(option).strip() for option in options_raw if str(option).strip()]


def _parse_timeout_seconds(parameters: Dict[str, Any]) -> float:
    try:
        timeout_seconds = float(parameters.get("timeout_seconds", _DEFAULT_TIMEOUT_SECONDS))
    except (TypeError, ValueError):
        timeout_seconds = _DEFAULT_TIMEOUT_SECONDS
    return max(1.0, min(timeout_seconds, 3600.0))


def _interaction_port(context: ToolExecutionContext) -> Any | None:
    if context.capabilities is None:
        return None
    return context.capabilities.interaction


async def _cancelled_before_ask(context: ToolExecutionContext) -> bool:
    cancellation = getattr(context, "cancellation", None)
    return cancellation is not None and await cancellation.is_cancelled()


def _cancelled_result() -> ToolResult:
    return ToolResult(
        success=False,
        error="run cancelled before answer",
        error_code="CANCELLED",
    )


def _background_task_id(context: ToolExecutionContext, intent: str) -> str | None:
    if not intent.startswith("background"):
        return None
    agent_id = str(getattr(context, "agent_id", "") or "")
    if not agent_id.startswith(_BACKGROUND_AGENT_PREFIX):
        return None
    candidate = agent_id[len(_BACKGROUND_AGENT_PREFIX) :].strip()
    return candidate or None


def _background_port(context: ToolExecutionContext) -> Any | None:
    if context.capabilities is None:
        return None
    return context.capabilities.background


def _build_ask_request(
    parameters: Dict[str, Any],
    context: ToolExecutionContext,
    *,
    session_id: str,
    intent: str,
    question: str,
) -> _AskRequest:
    return _AskRequest(
        session_id=session_id,
        user_id=_optional_env_text(context, "user_id"),
        turn_id=_optional_env_text(context, "turn_id"),
        intent=intent,
        question=question,
        options=_parse_options(parameters),
        allow_free_text=bool(parameters.get("allow_free_text", True)),
        timeout_seconds=_parse_timeout_seconds(parameters),
    )


def _ask_kwargs(
    request: _AskRequest,
    context: ToolExecutionContext,
) -> dict[str, Any]:
    cancellation = getattr(context, "cancellation", None)
    return {
        "session_id": request.session_id,
        "user_id": request.user_id,
        "turn_id": request.turn_id,
        "question": request.question,
        "options": request.options,
        "allow_free_text": request.allow_free_text,
        "timeout_seconds": request.timeout_seconds,
        "background": request.intent.startswith("background"),
        "background_task_id": _background_task_id(context, request.intent),
        "background_port": _background_port(context),
        "cancellation": cancellation,
    }


def _map_outcome(outcome: Any, timeout_seconds: float) -> ToolResult:
    if outcome.resolution == "cancelled":
        return _cancelled_result()
    if outcome.timed_out:
        return ToolResult(
            success=False,
            error=f"no answer within {timeout_seconds:.0f}s",
        )
    return ToolResult(success=True, data={"answer": outcome.answer or ""})


def _ask_parameters() -> list[ToolParameter]:
    return [
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
    ]


def _ask_metadata() -> dict[str, Any]:
    return {
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
    }


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
            effect_replay_policy="non_idempotent",
            parameters=_ask_parameters(),
            tags=["control", "ask"],
            timeout=600,
            metadata=_ask_metadata(),
        )

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        session_id = _env_text(context, "session_id")
        if not session_id:
            return ToolResult(
                success=False,
                error="ask_user_question requires an active session",
            )

        intent = _env_text(context, "intent")
        if intent.startswith("background") and not _background_ask_allowed(context):
            return ToolResult(
                success=False,
                error=(
                    "ask_user_question is not allowed from background "
                    "context without the 'allow_ask_in_background' flag"
                ),
            )

        question = _parse_question(parameters)
        if not question:
            return ToolResult(
                success=False,
                error="ask_user_question requires a non-empty 'question'",
            )

        interaction = _interaction_port(context)
        if interaction is None:
            return ToolResult(
                success=False,
                error="ask_user_question requires the interaction capability",
            )

        if await _cancelled_before_ask(context):
            return _cancelled_result()

        request = _build_ask_request(
            parameters,
            context,
            session_id=session_id,
            intent=intent,
            question=question,
        )

        try:
            outcome = await interaction.ask(**_ask_kwargs(request, context))
        except RuntimeError as exc:
            return ToolResult(success=False, error=str(exc))

        return _map_outcome(outcome, request.timeout_seconds)


__all__ = ["AskUserQuestionTool"]
