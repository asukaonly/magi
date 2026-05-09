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
from typing import Any, Dict, List, Optional

from ...config.models import LLMScenario, ThinkingDepth
from ...llm.provider_bridge import LLMProviderBridge

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Models with an effective window smaller than this skip LLM summarisation
# and fall back to rule-based truncation (the summarisation prompt + history
# would not fit).
_LLM_COMPACT_MIN_WINDOW = 65_536

# How many recent API-round groups to keep *after* compaction so the model
# still sees the most recent exchange.
_KEEP_RECENT_ROUNDS = 3

# Rule-based fallback: keep the N most recent messages when we cannot run
# the LLM summariser.
_RULE_KEEP_RECENT_MESSAGES = 10

# Safety margin subtracted from the effective window in addition to the
# output-token and summary-token reserves.
_SAFETY_BUFFER_TOKENS = 8_192

# Maximum tokens reserved for the compaction summary output.
_SUMMARY_OUTPUT_RESERVE = 16_384

# Output reserve for the main model response.
_OUTPUT_RESERVE = 8_192

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
    try:
        text = json.dumps(messages, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(messages)
    return max(1, len(text) // _CHARS_PER_TOKEN_ESTIMATE)


def _get_effective_context_window(
    context_window: int | None,
) -> int:
    """Return the usable context window after reserves."""
    if context_window is None or context_window <= 0:
        # Conservative fallback when the window is unknown.
        return 128_000
    return context_window


def _compute_compact_threshold(effective_window: int) -> int:
    """Return the token count at which compaction should trigger."""
    usable = effective_window - _OUTPUT_RESERVE - _SUMMARY_OUTPUT_RESERVE - _SAFETY_BUFFER_TOKENS
    return max(usable, 0)


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
        on_event: Any | None = None,
    ) -> None:
        self._scenario_llm_pool = scenario_llm_pool
        self._context_window = context_window
        self._on_event = on_event
        self._consecutive_failures = 0
        # Track the last provider-reported input token count so that
        # callers can feed us an accurate number.
        self._last_input_tokens: int | None = None

    # -- configuration helpers ------------------------------------------------

    @property
    def effective_window(self) -> int:
        return _get_effective_context_window(self._context_window)

    @property
    def compact_threshold(self) -> int:
        return _compute_compact_threshold(self.effective_window)

    def update_context_window(self, context_window: int | None) -> None:
        if context_window is not None and context_window > 0:
            self._context_window = context_window

    # -- token tracking -------------------------------------------------------

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

    def _current_token_estimate(self, messages: List[Dict[str, Any]]) -> int:
        """Best-effort token count: prefer provider-reported, else estimate."""
        if self._last_input_tokens is not None and self._last_input_tokens > 0:
            return self._last_input_tokens
        return _estimate_message_tokens(messages)

    # -- decision -------------------------------------------------------------

    def should_compact(self, messages: List[Dict[str, Any]]) -> bool:
        """Return True when the messages are close enough to the limit."""
        if self._consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
            logger.warning(
                "[ContextCompactor] Circuit breaker open (%d consecutive failures), skipping compaction",
                self._consecutive_failures,
            )
            return False
        token_count = self._current_token_estimate(messages)
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
        original_count = len(messages)

        if self.effective_window < _LLM_COMPACT_MIN_WINDOW:
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
        if len(groups) <= _KEEP_RECENT_ROUNDS:
            return CompactionResult(
                compacted=False,
                messages=messages,
                original_message_count=len(messages),
                kept_message_count=len(messages),
            )

        # Split: older groups → summarise, recent groups → keep verbatim.
        older_groups = groups[:-_KEEP_RECENT_ROUNDS]
        recent_groups = groups[-_KEEP_RECENT_ROUNDS:]
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
        from ...llm.scenario_pool import ScenarioLLMPool

        pool: ScenarioLLMPool = self._scenario_llm_pool
        try:
            adapter = pool.get(LLMScenario.CONTEXT_COMPACT)
        except (ValueError, KeyError):
            logger.info("[ContextCompactor] CONTEXT_COMPACT scenario not configured, falling back to CORE")
            adapter = pool.get(LLMScenario.CORE)

        bridge = LLMProviderBridge(adapter)
        response = await bridge.chat(
            system_prompt=_COMPACT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=_SUMMARY_OUTPUT_RESERVE,
            temperature=0.2,
            thinking_depth=ThinkingDepth.NONE,
            event_context={
                "request_kind": "memory:context_compact",
                "agent_id": "context_compactor",
            },
        )
        return response.content.strip()

    # -- Rule-based fallback --------------------------------------------------

    def _rule_based_compact(
        self,
        messages: List[Dict[str, Any]],
    ) -> CompactionResult:
        """Drop oldest messages, keeping only the most recent ones."""
        if len(messages) <= _RULE_KEEP_RECENT_MESSAGES:
            return CompactionResult(
                compacted=False,
                messages=messages,
                original_message_count=len(messages),
                kept_message_count=len(messages),
            )

        kept = messages[-_RULE_KEEP_RECENT_MESSAGES:]
        boundary: Dict[str, Any] = {
            "role": "system",
            "content": (
                "[context truncated] Older messages have been removed to stay "
                "within the context window. The most recent exchanges follow."
            ),
        }
        compacted = [boundary] + kept

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
