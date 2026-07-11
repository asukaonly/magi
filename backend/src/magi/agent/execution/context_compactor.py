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
    build_context_window_budget,
    estimate_context_tokens,
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

# Maximum tokens reserved for the compaction summary output.
_SUMMARY_OUTPUT_RESERVE = 16_384
_SUMMARY_INPUT_RATIO = 0.60

# Cheap per-character token estimate (JSON encoded messages) used when no
# provider-reported token count is available.
_CHARS_PER_TOKEN_ESTIMATE = 4

# Maximum consecutive compaction failures before the circuit breaker trips.
_MAX_CONSECUTIVE_FAILURES = 3


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


def _flatten_groups(groups: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    return [msg for group in groups for msg in group]


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

    @property
    def history_token_budget(self) -> int:
        return self.compact_threshold

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
        payload = {"messages": messages, "overhead": prompt_overhead}
        message_estimate = _estimate_message_tokens([payload])
        if self._last_input_tokens is not None and self._last_input_tokens > 0:
            return max(self._last_input_tokens, message_estimate)
        return message_estimate

    # -- decision -------------------------------------------------------------

    def should_compact(
        self,
        messages: List[Dict[str, Any]],
        *,
        prompt_overhead: Any | None = None,
    ) -> bool:
        """Return True when the messages are close enough to the limit."""
        token_count = self._current_token_estimate(
            messages,
            prompt_overhead=prompt_overhead,
        )
        threshold = self.compact_threshold
        above = token_count >= threshold
        if above:
            logger.info(
                "[ContextCompactor] Token count %d >= threshold %d (window=%d), compaction needed",
                token_count, threshold, self.effective_window,
            )
        return above

    # -- compaction -----------------------------------------------------------

    async def compact(
        self,
        messages: List[Dict[str, Any]],
        system_prompt: str = "",
    ) -> CompactionResult:
        """Run compaction and return the replacement message list."""
        if self._consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
            logger.warning(
                "[ContextCompactor] Summary circuit breaker open (%d consecutive failures), using rule fallback",
                self._consecutive_failures,
            )
            return self._rule_based_compact(messages)

        if self._scenario_llm_pool is None:
            logger.warning("[ContextCompactor] No scenario LLM pool configured, falling back to rule-based compaction")
            return self._rule_based_compact(messages)

        try:
            return await self._llm_compact(messages, system_prompt)
        except Exception:
            self._consecutive_failures += 1
            logger.exception(
                "[ContextCompactor] LLM compaction failed (consecutive=%d), falling back to rule-based",
                self._consecutive_failures,
            )
            return self._rule_based_compact(messages)

    # -- LLM-based compaction -------------------------------------------------

    async def _llm_compact(
        self,
        messages: List[Dict[str, Any]],
        system_prompt: str,
    ) -> CompactionResult:
        """Summarise older messages via LLM and replace them."""
        groups = _group_messages_by_round(messages)
        if len(groups) <= 1:
            return self._rule_based_compact(messages)

        # Split: older groups → summarise, recent groups → keep verbatim.
        recent_group_count = min(_KEEP_RECENT_ROUNDS, len(groups) - 1)
        older_groups = groups[:-recent_group_count]
        recent_groups = groups[-recent_group_count:]
        older_messages = _flatten_groups(older_groups)
        recent_messages = _flatten_groups(recent_groups)

        # Build human-readable conversation text for the summariser.
        conversation_text = self._render_messages_for_summary(older_messages)
        user_prompt = _COMPACT_USER_TEMPLATE.format(conversation_text=conversation_text)

        await self._emit_event("context_compacting", {
            "older_message_count": len(older_messages),
            "recent_message_count": len(recent_messages),
            "estimated_tokens": _estimate_message_tokens(older_messages),
        })

        start = time.monotonic()
        summary_text = await self._call_summariser(user_prompt)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        boundary_message: Dict[str, Any] = {
            "role": "system",
            "content": (
                "[context compacted] The earlier conversation has been summarised. "
                "Details below reflect the key context from the prior exchange.\n\n"
                + summary_text
            ),
        }
        compacted_messages = [boundary_message] + recent_messages

        self._consecutive_failures = 0
        self._last_input_tokens = None  # Reset — message list changed.

        await self._emit_event("context_compacted", {
            "original_count": len(messages),
            "compacted_count": len(compacted_messages),
            "summary_length": len(summary_text),
            "elapsed_ms": elapsed_ms,
        })

        logger.info(
            "[ContextCompactor] LLM compaction: %d → %d messages (%d ms)",
            len(messages), len(compacted_messages), elapsed_ms,
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
        chunk_chars = max(
            4_000,
            int(budget.input_capacity * _SUMMARY_INPUT_RATIO) * _CHARS_PER_TOKEN_ESTIMATE,
        )
        chunks = self._split_summary_prompt(user_prompt, max_chars=chunk_chars)
        bridge = LLMProviderBridge(resolved.adapter)
        cumulative_summary = ""
        for index, chunk in enumerate(chunks):
            prompt = chunk
            if cumulative_summary:
                prompt = (
                    "Merge the previous partial summary with the next conversation chunk. "
                    "Return one cumulative summary using the required analysis and summary blocks.\n\n"
                    f"<previous_summary>\n{cumulative_summary}\n</previous_summary>\n\n"
                    f"<next_conversation_chunk>\n{chunk}\n</next_conversation_chunk>"
                )
            response = await bridge.chat(
                system_prompt=_COMPACT_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=min(_SUMMARY_OUTPUT_RESERVE, budget.output_reserve),
                temperature=0.2,
                thinking_depth=ThinkingDepth.NONE,
                event_context={
                    "request_kind": "memory:context_compact",
                    "agent_id": "context_compactor",
                    "chunk_index": index,
                    "chunk_count": len(chunks),
                },
            )
            cumulative_summary = str(response.content or "").strip()
            if not cumulative_summary:
                raise RuntimeError("Context compaction summary was empty")
        return cumulative_summary

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

    @staticmethod
    def _split_summary_prompt(text: str, *, max_chars: int) -> list[str]:
        if len(text) <= max_chars:
            return [text]
        return [text[start : start + max_chars] for start in range(0, len(text), max_chars)]

    # -- Rule-based fallback --------------------------------------------------

    def _rule_based_compact(
        self,
        messages: List[Dict[str, Any]],
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

        if len(messages) <= _RULE_KEEP_RECENT_MESSAGES:
            kept = list(messages)
        else:
            groups = _group_messages_by_round(messages)
            selected_groups: list[list[dict[str, Any]]] = []
            selected_count = 0
            for group in reversed(groups):
                if selected_groups and selected_count + len(group) > _RULE_KEEP_RECENT_MESSAGES:
                    break
                selected_groups.append(group)
                selected_count += len(group)
                if selected_count >= _RULE_KEEP_RECENT_MESSAGES:
                    break
            kept = _flatten_groups(list(reversed(selected_groups)))
        kept = self._truncate_messages_to_tail_budget(kept)
        boundary: Dict[str, Any] = {
            "role": "system",
            "content": (
                "[context truncated] Older messages have been removed to stay "
                "within the context window. The most recent exchanges follow."
            ),
        }
        compacted = [boundary] + kept
        self._last_input_tokens = None

        logger.info(
            "[ContextCompactor] Rule-based compaction: %d → %d messages",
            len(messages), len(compacted),
        )

        return CompactionResult(
            compacted=True,
            messages=compacted,
            original_message_count=len(messages),
            kept_message_count=len(compacted),
        )

    def _truncate_messages_to_tail_budget(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not messages:
            return []
        tail_token_budget = self._current_budget().recent_tail_tokens
        if _estimate_message_tokens(messages) <= tail_token_budget:
            return list(messages)
        per_message_chars = max(
            1_000,
            tail_token_budget * _CHARS_PER_TOKEN_ESTIMATE // len(messages),
        )
        compacted: list[dict[str, Any]] = []
        for message in messages:
            copied = dict(message)
            content = copied.get("content")
            if isinstance(content, str) and len(content) > per_message_chars:
                marker = "\n... [truncated] ...\n"
                side_chars = max(1, (per_message_chars - len(marker)) // 2)
                copied["content"] = (
                    content[:side_chars].rstrip()
                    + marker
                    + content[-side_chars:].lstrip()
                )
            compacted.append(copied)
        return compacted

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
                # Truncate very long tool results.
                if isinstance(content, str) and len(content) > 2000:
                    content = content[:2000] + "\n... [truncated]"
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
                                tool_name = block.get("name", "?")
                                tool_input = json.dumps(
                                    block.get("input", {}),
                                    ensure_ascii=False,
                                    default=str,
                                )
                                if len(tool_input) > 800:
                                    tool_input = tool_input[:800] + "..."
                                text_parts.append(f"[call {tool_name}({tool_input})]")
                    text = "\n".join(text_parts)
                else:
                    text = str(content)
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
