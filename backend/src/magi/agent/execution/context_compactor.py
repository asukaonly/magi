"""Context window compaction for function-calling loops.

When the accumulated messages approach the active model's context window
limit, this module summarises older conversation history via an LLM call
(or falls back to rule-based truncation for small-window models) and
replaces the original messages with a compact boundary + summary.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List

from ...config.models import LLMScenario, ThinkingDepth
from ...context.window_budget import (
    ContextWindowBudget,
    ContextWindowUsage,
    GENERAL_SUMMARY_OUTPUT_PROFILE,
    build_context_window_budget,
    estimate_context_tokens,
    measure_provider_prompt_usage,
    resolve_summary_output_tokens,
)
from ...context.summary_generation import (
    SummaryChunkRequest,
    generate_cumulative_summary,
    resolve_cumulative_summary_output_tokens,
)
from ...llm.model_context import (
    ModelContextProfile,
    ResolvedModel,
    unknown_model_context,
)
from ...llm.provider_bridge import LLMProviderBridge

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# How many recent API-round groups to keep *after* compaction so the model
# still sees the most recent exchange.
_KEEP_RECENT_ROUNDS = 3

# Rule-based fallback: keep the N most recent messages when we cannot run
# the LLM summariser.
_RULE_KEEP_RECENT_MESSAGES = 10

# Maximum consecutive compaction failures before the circuit breaker trips.
_MAX_CONSECUTIVE_FAILURES = 3
_CIRCUIT_RETRY_SECONDS = 60.0
_CONTEXT_BOUNDARY_ROLE = "user"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CompactionResult:
    """Outcome of a compaction attempt."""

    compacted: bool
    messages: List[Dict[str, Any]]
    summary_text: str = ""
    original_message_count: int = 0
    kept_message_count: int = 0
    failure_reason: str | None = None


# ---------------------------------------------------------------------------
# Compaction prompt
# ---------------------------------------------------------------------------

_COMPACT_SYSTEM_PROMPT = """\
You are a conversation summariser for an AI assistant.  Your ONLY job is
to produce a faithful, detail-preserving summary of the conversation
history provided by the user.

CRITICAL RULES:
- Respond with plain text only.  Do NOT call any tools.
- Your response MUST contain an <analysis> block followed by a <summary> block.
- Keep the complete response within {max_summary_tokens} tokens.

<analysis>
Chronologically walk through the conversation.  For each exchange note:
1. The user's explicit request and intent
2. The approach taken and key decisions
3. Specific file paths, code snippets, function signatures, and edits
4. Errors encountered and how they were fixed
5. User feedback and corrections
</analysis>

<summary>
Produce a structured summary covering:
1. Primary request and intent
2. Key technical context (languages, frameworks, libraries)
3. Files and code sections examined or modified (include short snippets when important)
4. Errors, root causes, and fixes applied
5. Current task status and any pending work
6. Decisions made and rationale
</summary>
"""

_COMPACT_USER_TEMPLATE = """\
Summarise the conversation history below.  Preserve every file path, \
code snippet, function signature, and technical detail that would be \
needed to continue the work without re-reading the original messages.

<conversation>
{conversation_text}
</conversation>
"""


# ---------------------------------------------------------------------------
# Message grouping helpers
# ---------------------------------------------------------------------------


def _group_messages_by_round(messages: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Group messages into API rounds.

    Each round starts with an assistant message and includes all subsequent
    non-assistant messages (user replies, tool results) until the next
    assistant message.  If the conversation starts with user/system
    messages they form a leading group.
    """
    groups: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role", "")
        if role == "assistant" and current:
            groups.append(current)
            current = []
        current.append(msg)

    if current:
        groups.append(current)

    return groups


def _group_messages_by_user_turn(
    messages: List[Dict[str, Any]],
) -> List[List[Dict[str, Any]]]:
    """Group initial conversation history into complete user-led turns."""
    groups: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []

    for message in messages:
        if message.get("role") == "user" and current:
            groups.append(current)
            current = []
        current.append(message)

    if current:
        groups.append(current)

    return groups


def _flatten_groups(groups: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    return [msg for group in groups for msg in group]


def _latest_user_message(
    messages: List[Dict[str, Any]],
) -> Dict[str, Any] | None:
    for message in reversed(messages):
        if message.get("role") == "user":
            return message
    return None


def _contains_message(
    messages: List[Dict[str, Any]],
    target: Dict[str, Any] | None,
) -> bool:
    return target is not None and any(message is target for message in messages)


def _render_tool_call_for_summary(call: Any) -> str | None:
    if not isinstance(call, dict):
        return None
    function = call.get("function")
    function_payload = function if isinstance(function, dict) else {}
    tool_name = str(function_payload.get("name") or call.get("name") or "?")
    tool_input = function_payload.get("arguments")
    if tool_input is None:
        tool_input = call.get("input", {})
    if isinstance(tool_input, str):
        rendered_input = tool_input
    else:
        rendered_input = json.dumps(tool_input, ensure_ascii=False, default=str)
    call_id = str(call.get("id") or "").strip()
    id_suffix = f" id={call_id}" if call_id else ""
    return f"[call {tool_name}({rendered_input}){id_suffix}]"


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


def _estimate_message_tokens(messages: List[Dict[str, Any]]) -> int:
    """Cheap character-based token estimate."""
    return estimate_context_tokens(messages)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class ContextCompactor:
    """Monitors context size and compacts when approaching the limit."""

    def __init__(
        self,
        *,
        scenario_llm_pool: Any | None = None,
        context_window: int | None = None,
        budget_provider: Callable[[], ContextWindowBudget] | None = None,
        on_event: Any | None = None,
    ) -> None:
        self._scenario_llm_pool = scenario_llm_pool
        self._static_context_window = context_window
        self._budget_provider = budget_provider
        self._on_event = on_event
        self._consecutive_failures = 0
        self._circuit_opened_at: float | None = None
        # Track the last provider-reported input token count so that
        # callers can feed us an accurate number.
        self._last_input_tokens: int | None = None

    # -- configuration helpers ------------------------------------------------

    @property
    def effective_window(self) -> int:
        return self._current_budget().context_window

    @property
    def compact_threshold(self) -> int:
        return self._current_budget().compaction_trigger_tokens

    def _current_budget(self) -> ContextWindowBudget:
        if self._budget_provider is not None:
            return self._budget_provider()
        return build_context_window_budget(
            ModelContextProfile(
                provider_id="unknown",
                model_id="unknown",
                context_window=self._static_context_window,
                max_output_tokens=None,
            )
        )

    def update_context_window(self, context_window: int | None) -> None:
        if context_window is not None and context_window > 0:
            self._static_context_window = context_window

    # -- token tracking -------------------------------------------------------

    def begin_run(self) -> None:
        """Discard provider usage from an earlier execution run."""
        self._last_input_tokens = None

    def invalidate_recorded_usage(self) -> None:
        """Discard provider usage after the provider-facing prompt changes."""
        self._last_input_tokens = None

    def record_input_tokens(self, input_tokens: int) -> None:
        """Feed provider-reported input token count after each LLM call."""
        if input_tokens > 0:
            self._last_input_tokens = input_tokens

    def get_usage(self) -> dict[str, int] | None:
        """Return current context window usage snapshot, or *None* if unknown."""
        if self._last_input_tokens is None or self._last_input_tokens <= 0:
            return None
        return {
            "used_tokens": self._last_input_tokens,
            "window_size": self.effective_window,
            "threshold": self.compact_threshold,
        }

    def _current_token_estimate(
        self,
        messages: List[Dict[str, Any]],
        *,
        prompt_overhead: Any | None = None,
    ) -> int:
        """Best-effort token count: prefer provider-reported, else estimate."""
        return self.measure_usage(
            messages,
            prompt_overhead=prompt_overhead,
        ).estimated_tokens

    def measure_usage(
        self,
        messages: List[Dict[str, Any]],
        *,
        prompt_overhead: Any | None = None,
    ) -> ContextWindowUsage:
        """Measure the complete provider-facing input against the active budget."""
        return measure_provider_prompt_usage(
            self._current_budget(),
            messages,
            prompt_overhead=prompt_overhead,
            observed_input_tokens=self._last_input_tokens,
        )

    # -- decision -------------------------------------------------------------

    def should_compact(
        self,
        messages: List[Dict[str, Any]],
        *,
        prompt_overhead: Any | None = None,
    ) -> bool:
        """Return True when the messages are close enough to the limit."""
        usage = self.measure_usage(
            messages,
            prompt_overhead=prompt_overhead,
        )
        if usage.requires_compaction:
            logger.info(
                "[ContextCompactor] Token count %d >= threshold %d (window=%d), compaction needed",
                usage.estimated_tokens,
                usage.compaction_trigger_tokens,
                self.effective_window,
            )
        return usage.requires_compaction

    # -- compaction -----------------------------------------------------------

    async def compact(
        self,
        messages: List[Dict[str, Any]],
        system_prompt: str = "",
        *,
        preserve_user_turns: bool = False,
    ) -> CompactionResult:
        """Run compaction and return the replacement message list."""
        if self._circuit_blocks_summary_attempt():
            logger.warning(
                "[ContextCompactor] Summary circuit breaker open (%d consecutive failures), using rule fallback",
                self._consecutive_failures,
            )
            return self._rule_based_compact(
                messages,
                preserve_user_turns=preserve_user_turns,
            )

        if self._scenario_llm_pool is None:
            logger.warning(
                "[ContextCompactor] No scenario LLM pool configured, falling back to rule-based compaction"
            )
            return self._rule_based_compact(
                messages,
                preserve_user_turns=preserve_user_turns,
            )

        try:
            return await self._llm_compact(
                messages,
                system_prompt,
                preserve_user_turns=preserve_user_turns,
            )
        except Exception:
            self._consecutive_failures += 1
            if self._consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                self._circuit_opened_at = time.monotonic()
            logger.exception(
                "[ContextCompactor] LLM compaction failed (consecutive=%d), falling back to rule-based",
                self._consecutive_failures,
            )
            return self._rule_based_compact(
                messages,
                preserve_user_turns=preserve_user_turns,
            )

    def _circuit_blocks_summary_attempt(self) -> bool:
        if self._consecutive_failures < _MAX_CONSECUTIVE_FAILURES:
            return False
        now = time.monotonic()
        if self._circuit_opened_at is None:
            self._circuit_opened_at = now
            return True
        if now - self._circuit_opened_at < _CIRCUIT_RETRY_SECONDS:
            return True
        logger.info(
            "[ContextCompactor] Summary circuit breaker retry window reached; attempting recovery"
        )
        return False

    # -- LLM-based compaction -------------------------------------------------

    async def _llm_compact(
        self,
        messages: List[Dict[str, Any]],
        system_prompt: str,
        *,
        preserve_user_turns: bool,
    ) -> CompactionResult:
        """Summarise older messages via LLM and replace them."""
        groups = (
            _group_messages_by_user_turn(messages)
            if preserve_user_turns
            else _group_messages_by_round(messages)
        )
        if len(groups) <= 1:
            return self._rule_based_compact(
                messages,
                preserve_user_turns=preserve_user_turns,
            )

        # Split: older groups → summarise, recent groups → keep verbatim.
        max_recent_groups = min(_KEEP_RECENT_ROUNDS, len(groups) - 1)
        recent_groups = self._select_recent_groups(
            groups,
            max_groups=max_recent_groups,
        )
        older_groups = groups[: -len(recent_groups)]
        older_messages = _flatten_groups(older_groups)
        recent_messages = _flatten_groups(recent_groups)
        latest_user_message = _latest_user_message(messages)
        if _contains_message(older_messages, latest_user_message):
            older_messages = [
                message for message in older_messages if message is not latest_user_message
            ]
            assert latest_user_message is not None
            recent_messages = [latest_user_message, *recent_messages]
        if not older_messages:
            return self._rule_based_compact(
                messages,
                preserve_user_turns=preserve_user_turns,
            )

        # Build human-readable conversation text for the summariser.
        conversation_text = self._render_messages_for_summary(older_messages)
        user_prompt = _COMPACT_USER_TEMPLATE.format(conversation_text=conversation_text)

        await self._emit_event(
            "context_compacting",
            {
                "older_message_count": len(older_messages),
                "recent_message_count": len(recent_messages),
                "estimated_tokens": _estimate_message_tokens(older_messages),
            },
        )

        start = time.monotonic()
        summary_text = await self._call_summariser(user_prompt)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        boundary_message: Dict[str, Any] = {
            "role": _CONTEXT_BOUNDARY_ROLE,
            "content": (
                "[context compacted] The earlier conversation has been summarised. "
                "Details below reflect the key context from the prior exchange.\n\n" + summary_text
            ),
        }
        compacted_messages = [boundary_message] + recent_messages

        self._consecutive_failures = 0
        self._circuit_opened_at = None
        self._last_input_tokens = None  # Reset — message list changed.

        await self._emit_event(
            "context_compacted",
            {
                "original_count": len(messages),
                "compacted_count": len(compacted_messages),
                "summary_length": len(summary_text),
                "elapsed_ms": elapsed_ms,
            },
        )

        logger.info(
            "[ContextCompactor] LLM compaction: %d → %d messages (%d ms)",
            len(messages),
            len(compacted_messages),
            elapsed_ms,
        )

        return CompactionResult(
            compacted=True,
            messages=compacted_messages,
            summary_text=summary_text,
            original_message_count=len(messages),
            kept_message_count=len(compacted_messages),
        )

    async def _call_summariser(self, user_prompt: str) -> str:
        """Call the CONTEXT_COMPACT scenario model to produce a summary."""
        resolved = self._resolve_summary_model()
        budget = build_context_window_budget(resolved.context)
        summary_output_tokens = resolve_cumulative_summary_output_tokens(
            resolve_summary_output_tokens(
                self._current_budget(),
                budget,
                profile=GENERAL_SUMMARY_OUTPUT_PROFILE,
            ),
            input_capacity=budget.input_capacity,
        )
        bridge = LLMProviderBridge(resolved.adapter)
        system_prompt = _COMPACT_SYSTEM_PROMPT.format(
            max_summary_tokens=summary_output_tokens,
        )

        async def _call_chunk(request: SummaryChunkRequest) -> str:
            response = await bridge.chat(
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": request.prompt}],
                max_tokens=summary_output_tokens,
                temperature=0.2,
                thinking_depth=ThinkingDepth.NONE,
                event_context={
                    "request_kind": "memory:context_compact",
                    "agent_id": "context_compactor",
                    "chunk_index": request.index,
                    "chunk_final": request.is_final,
                },
            )
            return str(response.content or "").strip()

        summary = await generate_cumulative_summary(
            source_text=user_prompt,
            system_prompt=system_prompt,
            input_capacity=budget.input_capacity,
            build_prompt=self._build_cumulative_summary_prompt,
            call_chunk=_call_chunk,
        )
        if not summary:
            raise RuntimeError("Context compaction summary was empty")
        return summary

    @staticmethod
    def _build_cumulative_summary_prompt(previous_summary: str, source_chunk: str) -> str:
        if not previous_summary:
            return source_chunk
        return (
            "Merge the previous partial summary with the next conversation chunk. "
            "Return one cumulative summary using the required analysis and summary blocks.\n\n"
            f"<previous_summary>\n{previous_summary}\n</previous_summary>\n\n"
            f"<next_conversation_chunk>\n{source_chunk}\n</next_conversation_chunk>"
        )

    def _resolve_summary_model(self) -> ResolvedModel:
        pool = self._scenario_llm_pool
        resolver = getattr(pool, "resolve", None)
        getter = getattr(pool, "get", None)
        for scenario in (LLMScenario.CONTEXT_COMPACT, LLMScenario.CORE):
            try:
                if callable(resolver):
                    return resolver(scenario)
                if callable(getter):
                    adapter = getter(scenario)
                    return ResolvedModel(
                        adapter=adapter,
                        context=unknown_model_context(adapter),
                    )
            except (ValueError, KeyError):
                if scenario == LLMScenario.CONTEXT_COMPACT:
                    logger.info(
                        "[ContextCompactor] CONTEXT_COMPACT scenario not configured, falling back to CORE"
                    )
                    continue
                raise
        raise ValueError("No model is configured for context compaction")

    # -- Rule-based fallback --------------------------------------------------

    def _rule_based_compact(
        self,
        messages: List[Dict[str, Any]],
        *,
        preserve_user_turns: bool = False,
    ) -> CompactionResult:
        """Drop oldest messages, keeping only the most recent ones."""
        under_token_pressure = self._current_token_estimate(messages) >= self.compact_threshold
        if len(messages) <= _RULE_KEEP_RECENT_MESSAGES and not under_token_pressure:
            return CompactionResult(
                compacted=False,
                messages=messages,
                original_message_count=len(messages),
                kept_message_count=len(messages),
            )

        groups = (
            _group_messages_by_user_turn(messages)
            if preserve_user_turns
            else _group_messages_by_round(messages)
        )
        kept = self._select_recent_group_suffix(groups)
        latest_user_message = _latest_user_message(messages)
        if latest_user_message is not None and not _contains_message(
            kept,
            latest_user_message,
        ):
            kept = [latest_user_message, *kept]
        boundary: Dict[str, Any] = {
            "role": _CONTEXT_BOUNDARY_ROLE,
            "content": (
                "[context truncated] Older messages have been removed to stay "
                "within the context window. The most recent exchanges follow."
            ),
        }
        compacted = [boundary] + kept
        self._last_input_tokens = None

        logger.info(
            "[ContextCompactor] Rule-based compaction: %d → %d messages",
            len(messages),
            len(compacted),
        )

        return CompactionResult(
            compacted=True,
            messages=compacted,
            original_message_count=len(messages),
            kept_message_count=len(compacted),
        )

    def _select_recent_group_suffix(
        self,
        groups: list[list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        return _flatten_groups(
            self._select_recent_groups(
                groups,
                max_messages=_RULE_KEEP_RECENT_MESSAGES,
            )
        )

    def _select_recent_groups(
        self,
        groups: list[list[dict[str, Any]]],
        *,
        max_groups: int | None = None,
        max_messages: int | None = None,
    ) -> list[list[dict[str, Any]]]:
        if not groups:
            return []
        tail_token_budget = self._current_budget().recent_tail_tokens
        selected_reversed: list[list[dict[str, Any]]] = []
        selected_count = 0
        for group in reversed(groups):
            candidate_groups = list(reversed([*selected_reversed, group]))
            candidate_messages = _flatten_groups(candidate_groups)
            if selected_reversed and (
                (max_groups is not None and len(selected_reversed) >= max_groups)
                or (max_messages is not None and selected_count + len(group) > max_messages)
                or _estimate_message_tokens(candidate_messages) > tail_token_budget
            ):
                break
            selected_reversed.append(group)
            selected_count += len(group)
            if _estimate_message_tokens(candidate_messages) >= tail_token_budget:
                break
        return list(reversed(selected_reversed))

    # -- helpers --------------------------------------------------------------

    @staticmethod
    def _render_messages_for_summary(messages: List[Dict[str, Any]]) -> str:
        """Convert messages to a human-readable transcript for the summariser."""
        parts: List[str] = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")

            if role == "tool":
                tool_id = msg.get("tool_call_id", "?")
                parts.append(f"[tool result {tool_id}]: {content}")
            elif role == "assistant":
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    # Multi-block assistant messages (tool_use + text).
                    text_parts = []
                    for block in content:
                        if isinstance(block, dict):
                            if block.get("type") == "text":
                                text_parts.append(block.get("text", ""))
                            elif block.get("type") == "tool_use":
                                rendered_call = _render_tool_call_for_summary(block)
                                if rendered_call:
                                    text_parts.append(rendered_call)
                    text = "\n".join(text_parts)
                else:
                    text = str(content)
                tool_calls = msg.get("tool_calls")
                if isinstance(tool_calls, list):
                    rendered_calls = [
                        rendered
                        for call in tool_calls
                        if (rendered := _render_tool_call_for_summary(call)) is not None
                    ]
                    if rendered_calls:
                        text = "\n".join(part for part in [text, *rendered_calls] if part)
                parts.append(f"assistant: {text}")
            else:
                parts.append(f"{role}: {content}")

        return "\n\n".join(parts)

    async def _emit_event(self, stage: str, data: Dict[str, Any]) -> None:
        if self._on_event is not None:
            try:
                cb = self._on_event
                payload = {"stage": stage, **data}
                if callable(cb):
                    result = cb(payload)
                    if hasattr(result, "__await__"):
                        await result
            except Exception:
                logger.debug("[ContextCompactor] Event emission error", exc_info=True)
