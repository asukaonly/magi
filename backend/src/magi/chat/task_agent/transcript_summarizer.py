"""Durable transcript summarization for chat session prompt history."""

from __future__ import annotations

import inspect
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from magi.chat import ChatContextSummaryRecord, ChatMessageRecord, ChatStore
from magi.chat.storage.serialization import extract_attachment_payloads
from magi.config.models import LLMScenario, ThinkingDepth
from magi.core.logger import get_logger
from magi.llm.provider_bridge import LLMProviderBridge
from magi.context.window_budget import (
    ContextWindowBudget,
    GENERAL_SUMMARY_OUTPUT_PROFILE,
    build_context_window_budget,
    estimate_context_tokens,
    estimate_text_tokens,
    resolve_summary_output_tokens,
)
from magi.context.summary_generation import (
    SummaryChunkRequest,
    generate_cumulative_summary,
    resolve_cumulative_summary_output_tokens,
)
from magi.llm.model_context import (
    ModelContextProfile,
    ResolvedModel,
    unknown_model_context,
)
from magi.agent.trace import now_wall_ms

logger = get_logger(__name__)

SUMMARY_KIND_TOKEN_BUDGET = "token_budget"
DEFAULT_MIN_MESSAGES_FOR_SUMMARY = 16
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
    turn_id: str | None = None
    attachments: list[dict[str, object]] = field(default_factory=list)

    def to_prompt_message(self) -> dict[str, str]:
        return {"role": self.role, "content": _render_message_content(self)}


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


@dataclass(slots=True)
class _TranscriptSummaryPlan:
    active_summary: ChatContextSummaryRecord | None
    transcript_messages: list[TranscriptMessageForSummary]
    tail_start_index: int
    current_token_count: int
    messages_to_summarize: list[TranscriptMessageForSummary]
    session_origin: str


class ChatTranscriptSummarizer:
    """Create persistent rolling summaries for long chat sessions."""

    def __init__(
        self,
        *,
        chat_store: ChatStore | None,
        scenario_llm_pool: Any | None = None,
        llm_adapter: Any | None = None,
        model_context_provider: Callable[[], ModelContextProfile] | None = None,
        summary_generator: SummaryGenerator | None = None,
        token_threshold: int | None = None,
        tail_token_budget: int | None = None,
        min_messages: int = DEFAULT_MIN_MESSAGES_FOR_SUMMARY,
    ) -> None:
        self._chat_store = chat_store
        self._scenario_llm_pool = scenario_llm_pool
        self._llm_adapter = llm_adapter
        self._model_context_provider = model_context_provider
        self._summary_generator = summary_generator
        self._token_threshold = max(1, token_threshold) if token_threshold is not None else None
        self._tail_token_budget = (
            max(1, tail_token_budget) if tail_token_budget is not None else None
        )
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
        snapshot_version = await self._chat_store.get_history_version(session_id)
        active_summary = await self._chat_store.get_active_context_summary(
            session_id=session_id,
            summary_kind=SUMMARY_KIND_TOKEN_BUDGET,
        )
        transcript_messages = self._prompt_messages_from_records(
            await self._chat_store.list_messages(
                session_id=session_id,
                start_message_id=(
                    active_summary.first_kept_message_id if active_summary is not None else None
                ),
            )
        )
        if await self._chat_store.get_history_version(session_id) != snapshot_version:
            return TranscriptSummaryResult(
                created=False,
                reason="history_changed_during_load",
            )
        summary_plan = self._build_summary_plan(
            active_summary=active_summary,
            transcript_messages=transcript_messages,
        )
        if isinstance(summary_plan, TranscriptSummaryResult):
            return summary_plan

        summary_text = await self._generate_summary(
            self._build_summary_input(session_id, summary_plan)
        )
        if not summary_text:
            return TranscriptSummaryResult(created=False, reason="summary_unavailable")
        if await self._chat_store.get_history_version(session_id) != snapshot_version:
            return TranscriptSummaryResult(
                created=False,
                reason="history_changed_during_summary",
                token_count_before=summary_plan.current_token_count,
            )

        summary_record = self._build_summary_record(
            session_id=session_id,
            summary_plan=summary_plan,
            summary_text=summary_text,
        )
        await self._chat_store.activate_context_summary(summary_record)
        self._log_activated_context_summary(session_id, summary_record)
        return self._created_summary_result(summary_record)

    def _build_summary_plan(
        self,
        *,
        active_summary: ChatContextSummaryRecord | None,
        transcript_messages: list[TranscriptMessageForSummary],
    ) -> _TranscriptSummaryPlan | TranscriptSummaryResult:
        range_start_index = self._find_message_index(
            transcript_messages,
            active_summary.first_kept_message_id if active_summary is not None else None,
        )
        if range_start_index is None:
            range_start_index = 0
        budget = self._current_budget()
        token_threshold = self._token_threshold or budget.compaction_trigger_tokens
        tail_token_budget = self._tail_token_budget or budget.recent_tail_tokens
        candidate_messages = transcript_messages[range_start_index:]
        current_token_count = self._estimate_current_prompt_tokens(
            active_summary_text=active_summary.summary_text if active_summary is not None else None,
            messages=candidate_messages,
        )
        if current_token_count < token_threshold:
            reason = (
                "too_few_messages"
                if len(transcript_messages) < self._min_messages
                else "below_threshold"
            )
            return TranscriptSummaryResult(
                created=False,
                reason=reason,
                token_count_before=current_token_count,
            )

        tail_start_index = self._select_tail_start_index(
            transcript_messages,
            tail_token_budget=tail_token_budget,
        )
        if tail_start_index <= range_start_index:
            return TranscriptSummaryResult(created=False, reason="tail_within_budget")

        messages_to_summarize = transcript_messages[range_start_index:tail_start_index]
        if not messages_to_summarize:
            return TranscriptSummaryResult(created=False, reason="no_new_range")

        session_origin = (
            active_summary.session_origin
            if active_summary is not None and active_summary.session_origin.strip()
            else self._derive_session_origin(transcript_messages)
        )
        return _TranscriptSummaryPlan(
            active_summary=active_summary,
            transcript_messages=transcript_messages,
            tail_start_index=tail_start_index,
            current_token_count=current_token_count,
            messages_to_summarize=messages_to_summarize,
            session_origin=session_origin,
        )

    @staticmethod
    def _build_summary_input(
        session_id: str,
        summary_plan: _TranscriptSummaryPlan,
    ) -> TranscriptSummaryInput:
        return TranscriptSummaryInput(
            session_id=session_id,
            previous_summary=(
                summary_plan.active_summary.summary_text
                if summary_plan.active_summary is not None
                else None
            ),
            session_origin=summary_plan.session_origin,
            messages=summary_plan.messages_to_summarize,
        )

    def _build_summary_record(
        self,
        *,
        session_id: str,
        summary_plan: _TranscriptSummaryPlan,
        summary_text: str,
    ) -> ChatContextSummaryRecord:
        active_summary = summary_plan.active_summary
        first_kept_message = summary_plan.transcript_messages[summary_plan.tail_start_index]
        covered_to_message = summary_plan.messages_to_summarize[-1]
        covered_from_message_id = (
            active_summary.covered_from_message_id
            if active_summary is not None and active_summary.covered_from_message_id
            else summary_plan.messages_to_summarize[0].message_id
        )
        now_ms = now_wall_ms()
        token_count_after = self._estimate_current_prompt_tokens(
            active_summary_text=summary_text,
            messages=summary_plan.transcript_messages[summary_plan.tail_start_index :],
        )
        return ChatContextSummaryRecord(
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
            session_origin=summary_plan.session_origin,
            summary_text=summary_text,
            prompt_profile="general_chat",
            model_provider=self._resolve_model_provider(),
            model_id=self._resolve_model_id(),
            token_count_before=summary_plan.current_token_count,
            token_count_after=token_count_after,
            quality_status="generated",
            created_at_ms=now_ms,
            updated_at_ms=now_ms,
        )

    @staticmethod
    def _log_activated_context_summary(
        session_id: str,
        summary_record: ChatContextSummaryRecord,
    ) -> None:
        logger.info(
            "Activated chat context summary | session_id=%s summary_id=%s covered_to=%s first_kept=%s",
            session_id,
            summary_record.summary_id,
            summary_record.covered_to_message_id,
            summary_record.first_kept_message_id,
        )

    @staticmethod
    def _created_summary_result(
        summary_record: ChatContextSummaryRecord,
    ) -> TranscriptSummaryResult:
        return TranscriptSummaryResult(
            created=True,
            reason="created",
            summary_id=summary_record.summary_id,
            parent_summary_id=summary_record.parent_summary_id,
            covered_to_message_id=summary_record.covered_to_message_id,
            first_kept_message_id=summary_record.first_kept_message_id,
            token_count_before=summary_record.token_count_before,
            token_count_after=summary_record.token_count_after,
        )

    async def _generate_summary(self, summary_input: TranscriptSummaryInput) -> str:
        if self._summary_generator is not None:
            generated = self._summary_generator(summary_input)
            if inspect.isawaitable(generated):
                generated = await generated
            return str(generated or "").strip()
        resolved = self._resolve_summary_model()
        if resolved is None:
            return ""
        budget = build_context_window_budget(resolved.context)
        summary_output_tokens = resolve_cumulative_summary_output_tokens(
            self._resolve_summary_output_tokens(budget),
            input_capacity=budget.input_capacity,
        )
        bridge = LLMProviderBridge(resolved.adapter)

        system_prompt = self._build_system_prompt(summary_output_tokens)

        async def _call_chunk(request: SummaryChunkRequest) -> str:
            response = await bridge.chat(
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": request.prompt}],
                max_tokens=summary_output_tokens,
                temperature=0.2,
                thinking_depth=ThinkingDepth.NONE,
                event_context={
                    "request_kind": "memory:chat_transcript_summary",
                    "agent_id": "chat_transcript_summarizer",
                    "session_id": summary_input.session_id,
                    "chunk_index": request.index,
                    "chunk_final": request.is_final,
                },
            )
            return str(response.content or "").strip()

        return await generate_cumulative_summary(
            source_text=self._build_user_prompt(summary_input),
            system_prompt=system_prompt,
            input_capacity=budget.input_capacity,
            build_prompt=self._build_cumulative_prompt,
            call_chunk=_call_chunk,
        )

    @staticmethod
    def _build_cumulative_prompt(previous_summary: str, source_chunk: str) -> str:
        if not previous_summary:
            return source_chunk
        return (
            "Merge the previous partial summary with the next transcript chunk. "
            "Return one cumulative active summary only.\n\n"
            f"# Previous Partial Summary\n{previous_summary}\n\n"
            f"# Next Transcript Chunk\n{source_chunk}"
        )

    def _resolve_summary_model(self) -> ResolvedModel | None:
        if self._scenario_llm_pool is not None:
            resolver = getattr(self._scenario_llm_pool, "resolve", None)
            getter = getattr(self._scenario_llm_pool, "get", None)
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
                            "CONTEXT_COMPACT scenario not configured, falling back to CORE for chat transcript summary"
                        )
                        continue
                    return None
            return None
        if self._llm_adapter is None:
            return None
        return ResolvedModel(
            adapter=self._llm_adapter,
            context=unknown_model_context(self._llm_adapter),
        )

    def _resolve_summary_output_tokens(
        self,
        summary_model_budget: ContextWindowBudget,
    ) -> int:
        return resolve_summary_output_tokens(
            self._current_budget(),
            summary_model_budget,
            profile=GENERAL_SUMMARY_OUTPUT_PROFILE,
        )

    def _resolve_model_provider(self) -> str | None:
        resolved = self._resolve_summary_model()
        if resolved is None:
            return "test" if self._summary_generator is not None else None
        return resolved.context.provider_id

    def _resolve_model_id(self) -> str | None:
        resolved = self._resolve_summary_model()
        if resolved is None:
            return "summary_generator" if self._summary_generator is not None else None
        return resolved.context.model_id

    @staticmethod
    def _prompt_messages_from_records(
        records: list[ChatMessageRecord],
    ) -> list[TranscriptMessageForSummary]:
        messages: list[TranscriptMessageForSummary] = []
        for record in records:
            if not record.is_visible or record.replaced_by_message_id is not None:
                continue
            if record.message_kind not in _PROMPT_MESSAGE_KINDS:
                continue
            attachments = extract_attachment_payloads(record.payload_json)
            content = str(record.content_text or "").strip()
            if not content and not attachments:
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
                    turn_id=str(record.turn_id or "").strip() or None,
                    attachments=attachments,
                )
            )
        return messages

    def _current_budget(self):
        profile = (
            self._model_context_provider()
            if self._model_context_provider is not None
            else ModelContextProfile(
                provider_id="unknown",
                model_id="unknown",
                context_window=None,
                max_output_tokens=None,
            )
        )
        return build_context_window_budget(profile)

    def _select_tail_start_index(
        self,
        messages: list[TranscriptMessageForSummary],
        *,
        tail_token_budget: int,
    ) -> int:
        groups = self._group_messages_by_user_turn(messages)
        total_tokens = 0
        selected_groups = 0
        for start_index, end_index in reversed(groups):
            group_tokens = self._estimate_prompt_messages_tokens(
                [message.to_prompt_message() for message in messages[start_index:end_index]]
            )
            if selected_groups and total_tokens + group_tokens > tail_token_budget:
                break
            total_tokens += group_tokens
            selected_groups += 1
            if total_tokens >= tail_token_budget:
                break
        if not groups:
            return 0
        return groups[-max(1, selected_groups)][0]

    @staticmethod
    def _group_messages_by_user_turn(
        messages: list[TranscriptMessageForSummary],
    ) -> list[tuple[int, int]]:
        groups: list[tuple[int, int]] = []
        group_start = 0
        for index, message in enumerate(messages):
            if index > group_start and message.role == "user":
                groups.append((group_start, index))
                group_start = index
        if messages:
            groups.append((group_start, len(messages)))
        return groups

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
        summary_tokens = estimate_text_tokens(str(active_summary_text or ""))
        return summary_tokens + self._estimate_prompt_messages_tokens(
            [message.to_prompt_message() for message in messages]
        )

    @staticmethod
    def _estimate_prompt_messages_tokens(messages: list[dict[str, Any]]) -> int:
        return estimate_context_tokens(messages)

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
    def _build_system_prompt(max_summary_tokens: int) -> str:
        return f"""You create durable rolling summaries for an AI chat session.

Rules:
- Preserve user intent, decisions, constraints, names, IDs, file paths, code references, and unresolved tasks.
- Preserve attachment IDs and names so earlier session files remain addressable.
- If a previous summary is provided, merge it with the new transcript range into one cumulative summary.
- Do not mention that older messages were hidden or deleted.
- Write concise, structured plain text that can be inserted into a future prompt.
- Keep the summary within {max_summary_tokens} tokens.
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
            sections.extend(
                [
                    "# Previous Active Summary",
                    summary_input.previous_summary,
                    "",
                ]
            )
        sections.extend(
            [
                "# New Transcript Range",
                ChatTranscriptSummarizer._render_messages(summary_input.messages),
                "",
                "Return the new cumulative active summary only.",
            ]
        )
        return "\n".join(sections).strip()

    @staticmethod
    def _render_messages(messages: list[TranscriptMessageForSummary]) -> str:
        rendered: list[str] = []
        for message in messages:
            rendered.append(
                f"[{message.sequence_no}] {message.role} ({message.message_id}):\n"
                f"{_render_message_content(message)}"
            )
        return "\n\n".join(rendered)


def _render_message_content(message: TranscriptMessageForSummary) -> str:
    if not message.attachments:
        return message.content
    references = [
        {
            key: attachment[key]
            for key in (
                "attachment_id",
                "original_name",
                "kind",
                "mime_type",
                "page_count",
                "character_count",
                "parse_status",
            )
            if key in attachment
        }
        for attachment in message.attachments
    ]
    return (
        f"{message.content}\n\nAttachment references:\n"
        f"{json.dumps(references, ensure_ascii=False, default=str)}"
    )


__all__ = [
    "ChatTranscriptSummarizer",
    "TranscriptMessageForSummary",
    "TranscriptSummaryInput",
    "TranscriptSummaryResult",
]
