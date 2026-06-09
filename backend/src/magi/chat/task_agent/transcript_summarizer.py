"""Durable transcript summarization for chat session prompt history."""

from __future__ import annotations

import inspect
import json
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from magi.chat import ChatContextSummaryRecord, ChatMessageRecord, ChatStore
from magi.config.models import LLMScenario, ThinkingDepth
from magi.core.logger import get_logger
from magi.llm.provider_bridge import LLMProviderBridge
from magi.agent.message_utils import DEFAULT_HISTORY_TOKEN_BUDGET
from magi.agent.trace import now_wall_ms

logger = get_logger(__name__)

SUMMARY_KIND_TOKEN_BUDGET = "token_budget"
DEFAULT_SUMMARY_TRIGGER_TOKENS = int(DEFAULT_HISTORY_TOKEN_BUDGET * 0.75)
DEFAULT_SUMMARY_TAIL_TOKENS = int(DEFAULT_HISTORY_TOKEN_BUDGET * 0.25)
DEFAULT_MIN_MESSAGES_FOR_SUMMARY = 16
SUMMARY_OUTPUT_RESERVE = 8_192
_CHARS_PER_TOKEN_ESTIMATE = 4
_PROMPT_MESSAGE_KINDS = {"user_text", "assistant_final", "assistant_rhythm_segment"}


SummaryGenerator = Callable[["TranscriptSummaryInput"], str | Awaitable[str]]


@dataclass(slots=True)
class TranscriptMessageForSummary:
    """One transcript message selected for summary planning."""

    message_id: str
    role: str
    content: str
    sequence_no: int
    created_at_ms: int

    def to_prompt_message(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(slots=True)
class TranscriptSummaryInput:
    """Input passed to the summary generator."""

    session_id: str
    previous_summary: str | None
    session_origin: str
    messages: list[TranscriptMessageForSummary]


@dataclass(slots=True)
class TranscriptSummaryResult:
    """Outcome of one durable transcript summarization attempt."""

    created: bool
    reason: str
    summary_id: str | None = None
    parent_summary_id: str | None = None
    covered_to_message_id: str | None = None
    first_kept_message_id: str | None = None
    token_count_before: int | None = None
    token_count_after: int | None = None


class ChatTranscriptSummarizer:
    """Create persistent rolling summaries for long chat sessions."""

    def __init__(
        self,
        *,
        chat_store: ChatStore | None,
        scenario_llm_pool: Any | None = None,
        llm_adapter: Any | None = None,
        summary_generator: SummaryGenerator | None = None,
        token_threshold: int = DEFAULT_SUMMARY_TRIGGER_TOKENS,
        tail_token_budget: int = DEFAULT_SUMMARY_TAIL_TOKENS,
        min_messages: int = DEFAULT_MIN_MESSAGES_FOR_SUMMARY,
    ) -> None:
        self._chat_store = chat_store
        self._scenario_llm_pool = scenario_llm_pool
        self._llm_adapter = llm_adapter
        self._summary_generator = summary_generator
        self._token_threshold = max(1, token_threshold)
        self._tail_token_budget = max(1, tail_token_budget)
        self._min_messages = max(2, min_messages)
        self._session_locks: dict[str, Any] = {}

    async def maybe_summarize_session(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> TranscriptSummaryResult:
        """Generate and activate a new summary when a session tail is too large."""
        _ = user_id
        if self._chat_store is None:
            return TranscriptSummaryResult(created=False, reason="chat_store_unavailable")

        import asyncio

        lock = self._session_locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            return await self._maybe_summarize_session_locked(session_id=session_id)

    async def _maybe_summarize_session_locked(self, *, session_id: str) -> TranscriptSummaryResult:
        assert self._chat_store is not None
        active_summary = await self._chat_store.get_active_context_summary(
            session_id=session_id,
            summary_kind=SUMMARY_KIND_TOKEN_BUDGET,
        )
        transcript_messages = self._prompt_messages_from_records(
            await self._chat_store.list_messages(session_id=session_id)
        )
        if len(transcript_messages) < self._min_messages:
            return TranscriptSummaryResult(created=False, reason="too_few_messages")

        range_start_index = self._find_message_index(
            transcript_messages,
            active_summary.first_kept_message_id if active_summary is not None else None,
        )
        if range_start_index is None:
            range_start_index = 0
        tail_start_index = self._select_tail_start_index(transcript_messages)
        if tail_start_index <= range_start_index:
            return TranscriptSummaryResult(created=False, reason="tail_within_budget")

        candidate_messages = transcript_messages[range_start_index:]
        current_token_count = self._estimate_current_prompt_tokens(
            active_summary_text=active_summary.summary_text if active_summary is not None else None,
            messages=candidate_messages,
        )
        if current_token_count < self._token_threshold:
            return TranscriptSummaryResult(
                created=False,
                reason="below_threshold",
                token_count_before=current_token_count,
            )

        messages_to_summarize = transcript_messages[range_start_index:tail_start_index]
        if not messages_to_summarize:
            return TranscriptSummaryResult(created=False, reason="no_new_range")

        session_origin = (
            active_summary.session_origin
            if active_summary is not None and active_summary.session_origin.strip()
            else self._derive_session_origin(transcript_messages)
        )
        summary_input = TranscriptSummaryInput(
            session_id=session_id,
            previous_summary=(active_summary.summary_text if active_summary is not None else None),
            session_origin=session_origin,
            messages=messages_to_summarize,
        )
        summary_text = await self._generate_summary(summary_input)
        if not summary_text:
            return TranscriptSummaryResult(created=False, reason="summary_unavailable")

        first_kept_message = transcript_messages[tail_start_index]
        covered_to_message = messages_to_summarize[-1]
        covered_from_message_id = (
            active_summary.covered_from_message_id
            if active_summary is not None and active_summary.covered_from_message_id
            else messages_to_summarize[0].message_id
        )
        now_ms = now_wall_ms()
        token_count_after = self._estimate_current_prompt_tokens(
            active_summary_text=summary_text,
            messages=transcript_messages[tail_start_index:],
        )
        summary_record = ChatContextSummaryRecord(
            summary_id=f"summary_{uuid.uuid4().hex[:16]}",
            session_id=session_id,
            parent_summary_id=active_summary.summary_id if active_summary is not None else None,
            status="active",
            summary_kind=SUMMARY_KIND_TOKEN_BUDGET,
            persona_scope=None,
            covered_from_message_id=covered_from_message_id,
            covered_to_message_id=covered_to_message.message_id,
            first_kept_message_id=first_kept_message.message_id,
            covered_to_sequence_no=covered_to_message.sequence_no,
            session_origin=session_origin,
            summary_text=summary_text,
            prompt_profile="general_chat",
            model_provider=self._resolve_model_provider(),
            model_id=self._resolve_model_id(),
            token_count_before=current_token_count,
            token_count_after=token_count_after,
            quality_status="generated",
            created_at_ms=now_ms,
            updated_at_ms=now_ms,
        )
        await self._chat_store.activate_context_summary(summary_record)
        logger.info(
            "Activated chat context summary | session_id=%s summary_id=%s covered_to=%s first_kept=%s",
            session_id,
            summary_record.summary_id,
            summary_record.covered_to_message_id,
            summary_record.first_kept_message_id,
        )
        return TranscriptSummaryResult(
            created=True,
            reason="created",
            summary_id=summary_record.summary_id,
            parent_summary_id=summary_record.parent_summary_id,
            covered_to_message_id=summary_record.covered_to_message_id,
            first_kept_message_id=summary_record.first_kept_message_id,
            token_count_before=current_token_count,
            token_count_after=token_count_after,
        )

    async def _generate_summary(self, summary_input: TranscriptSummaryInput) -> str:
        if self._summary_generator is not None:
            generated = self._summary_generator(summary_input)
            if inspect.isawaitable(generated):
                generated = await generated
            return str(generated or "").strip()
        adapter = self._resolve_summary_adapter()
        if adapter is None:
            return ""
        bridge = LLMProviderBridge(adapter)
        response = await bridge.chat(
            system_prompt=self._build_system_prompt(),
            messages=[{"role": "user", "content": self._build_user_prompt(summary_input)}],
            max_tokens=SUMMARY_OUTPUT_RESERVE,
            temperature=0.2,
            thinking_depth=ThinkingDepth.NONE,
            event_context={
                "request_kind": "memory:chat_transcript_summary",
                "agent_id": "chat_transcript_summarizer",
                "session_id": summary_input.session_id,
            },
        )
        return str(response.content or "").strip()

    def _resolve_summary_adapter(self) -> Any | None:
        if self._scenario_llm_pool is not None:
            try:
                return self._scenario_llm_pool.get(LLMScenario.CONTEXT_COMPACT)
            except (ValueError, KeyError):
                logger.info("CONTEXT_COMPACT scenario not configured, falling back to CORE for chat transcript summary")
                try:
                    return self._scenario_llm_pool.get(LLMScenario.CORE)
                except (ValueError, KeyError):
                    return None
        return self._llm_adapter

    def _resolve_model_provider(self) -> str | None:
        adapter = self._resolve_summary_adapter()
        if adapter is None:
            return "test" if self._summary_generator is not None else None
        provider = getattr(adapter, "provider", None) or getattr(adapter, "provider_name", None)
        return str(provider) if provider is not None else None

    def _resolve_model_id(self) -> str | None:
        adapter = self._resolve_summary_adapter()
        if adapter is None:
            return "summary_generator" if self._summary_generator is not None else None
        model_id = getattr(adapter, "model_id", None) or getattr(adapter, "model_name", None)
        return str(model_id) if model_id is not None else None

    @staticmethod
    def _prompt_messages_from_records(records: list[ChatMessageRecord]) -> list[TranscriptMessageForSummary]:
        messages: list[TranscriptMessageForSummary] = []
        for record in records:
            if not record.is_visible or record.replaced_by_message_id is not None:
                continue
            if record.message_kind not in _PROMPT_MESSAGE_KINDS:
                continue
            content = str(record.content_text or "").strip()
            if not content:
                continue
            role = str(record.role or "").strip()
            if role not in {"user", "assistant"}:
                continue
            messages.append(
                TranscriptMessageForSummary(
                    message_id=record.message_id,
                    role=role,
                    content=content,
                    sequence_no=record.sequence_no,
                    created_at_ms=record.created_at_ms,
                )
            )
        return messages

    def _select_tail_start_index(self, messages: list[TranscriptMessageForSummary]) -> int:
        total_tokens = 0
        selected_count = 0
        for message in reversed(messages):
            message_tokens = self._estimate_prompt_messages_tokens([message.to_prompt_message()])
            if selected_count and total_tokens + message_tokens > self._tail_token_budget:
                break
            total_tokens += message_tokens
            selected_count += 1
            if total_tokens >= self._tail_token_budget:
                break
        return max(0, len(messages) - max(1, selected_count))

    @staticmethod
    def _find_message_index(
        messages: list[TranscriptMessageForSummary],
        message_id: str | None,
    ) -> int | None:
        normalized_id = str(message_id or "").strip()
        if not normalized_id:
            return None
        for index, message in enumerate(messages):
            if message.message_id == normalized_id:
                return index
        return None

    def _estimate_current_prompt_tokens(
        self,
        *,
        active_summary_text: str | None,
        messages: list[TranscriptMessageForSummary],
    ) -> int:
        summary_tokens = len(str(active_summary_text or "")) // _CHARS_PER_TOKEN_ESTIMATE
        return summary_tokens + self._estimate_prompt_messages_tokens(
            [message.to_prompt_message() for message in messages]
        )

    @staticmethod
    def _estimate_prompt_messages_tokens(messages: list[dict[str, Any]]) -> int:
        try:
            rendered = json.dumps(messages, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            rendered = str(messages)
        return max(1, len(rendered) // _CHARS_PER_TOKEN_ESTIMATE)

    @staticmethod
    def _derive_session_origin(messages: list[TranscriptMessageForSummary]) -> str:
        lines: list[str] = []
        for message in messages[:6]:
            content = message.content
            if len(content) > 240:
                content = content[:240].rstrip() + "..."
            label = "User" if message.role == "user" else "Assistant"
            lines.append(f"- {label}: {content}")
            if len(lines) >= 3:
                break
        if not lines:
            return "This session began before the retained raw transcript tail."
        return "The session began with these early exchanges:\n" + "\n".join(lines)

    @staticmethod
    def _build_system_prompt() -> str:
        return """You create durable rolling summaries for an AI chat session.

Rules:
- Preserve user intent, decisions, constraints, names, IDs, file paths, code references, and unresolved tasks.
- If a previous summary is provided, merge it with the new transcript range into one cumulative summary.
- Do not mention that older messages were hidden or deleted.
- Write concise, structured plain text that can be inserted into a future prompt.
- Keep the latest raw messages authoritative; summarize only the provided older range.
""".strip()

    @staticmethod
    def _build_user_prompt(summary_input: TranscriptSummaryInput) -> str:
        sections = [
            f"Session ID: {summary_input.session_id}",
            "",
            "# Session Origin",
            summary_input.session_origin,
            "",
        ]
        if summary_input.previous_summary:
            sections.extend([
                "# Previous Active Summary",
                summary_input.previous_summary,
                "",
            ])
        sections.extend([
            "# New Transcript Range",
            ChatTranscriptSummarizer._render_messages(summary_input.messages),
            "",
            "Return the new cumulative active summary only.",
        ])
        return "\n".join(sections).strip()

    @staticmethod
    def _render_messages(messages: list[TranscriptMessageForSummary]) -> str:
        rendered: list[str] = []
        for message in messages:
            content = message.content
            if len(content) > 4_000:
                content = content[:4_000].rstrip() + "\n... [truncated]"
            rendered.append(
                f"[{message.sequence_no}] {message.role} ({message.message_id}):\n{content}"
            )
        return "\n\n".join(rendered)


__all__ = [
    "ChatTranscriptSummarizer",
    "TranscriptMessageForSummary",
    "TranscriptSummaryInput",
    "TranscriptSummaryResult",
]
