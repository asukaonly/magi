"""Persona-boundary summarization for chat context assembly.

When a chat session's active persona changes mid-thread (the user
switches to a different assistant persona), prior turns produced by
the old persona must be **neutralized** into a continuity summary
before being fed back to the new persona — otherwise the LLM picks
up tone, jokes, and self-references from a voice the active persona
does not own.

This module is the L14 chat-domain side of that work. It is invoked
from :py:class:`ChatContextAssembler` during prompt assembly with
the raw history loaded by :py:class:`ChatReadService`, and returns:

* the trimmed tail (everything from the active persona's first turn
  onwards), which the assembler renders normally into the prompt;
* an optional neutral *continuity summary* that the assembler folds
  into ``session_summary`` ahead of the rendered tail.

The summarizer caches its output via the existing
``chat_context_summaries`` table (keyed by session_id + persona scope +
the message_id at the persona boundary) so subsequent turns for the
same active persona reuse the same summary instead of regenerating.

Lift criteria: this is per-chat-session prompt-assembly business
(L14). If voice / batch / scheduled drivers ever need the same
neutralization, lift the class up to a generic ring-2 location;
keep it local until then.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from magi.agent.trace import now_wall_ms
from magi.chat import ChatContextSummaryRecord, ChatStore
from magi.config.models import LLMScenario, ThinkingDepth
from magi.context.window_budget import (
    PERSONA_SUMMARY_OUTPUT_PROFILE,
    build_context_window_budget,
    resolve_summary_output_tokens,
)
from magi.context.summary_generation import (
    SummaryChunkRequest,
    generate_cumulative_summary,
    resolve_cumulative_summary_output_tokens,
)
from magi.core.logger import get_logger
from magi.llm.model_context import ResolvedModel, unknown_model_context
from magi.llm.provider_bridge import LLMProviderBridge

logger = get_logger(__name__)


# Persisted into ``chat_context_summaries.summary_kind`` so the
# session-summary read path can distinguish persona-boundary summaries
# from rolling token-budget summaries.
SUMMARY_KIND_PERSONA_BOUNDARY = "persona_boundary"


@dataclass(slots=True)
class PersonaBoundarySummaryMessage:
    """One transcript item selected for persona-boundary summarization."""

    message_id: str | None
    role: str
    content: str
    persona_id: str | None
    message_kind: str | None


@dataclass(slots=True)
class PersonaBoundarySummaryInput:
    """Input passed to the persona-boundary summary generator."""

    session_id: str
    active_persona_id: str
    messages: list[PersonaBoundarySummaryMessage]


PersonaBoundarySummaryGenerator = Callable[
    [PersonaBoundarySummaryInput],
    str | Awaitable[str],
]


def _normalize_persona_id(persona_id: str | None) -> str | None:
    """Strip + null-coalesce a persona id; matches the assembler's helper."""
    return str(persona_id or "").strip() or None


def _message_persona_id(item: Any) -> str | None:
    return _normalize_persona_id(getattr(item, "persona_id", None))


def _message_id(item: Any) -> str | None:
    return str(getattr(item, "message_id", "") or "").strip() or None


def _message_content(item: Any) -> str:
    to_prompt_message = getattr(item, "to_prompt_message", None)
    if callable(to_prompt_message):
        prompt_message = to_prompt_message()
        if isinstance(prompt_message, dict):
            return str(prompt_message.get("content") or "").strip()
    return str(getattr(item, "content", "") or "").strip()


class PersonaBoundarySummarizer:
    """Computes (and caches) the neutral continuity summary for a persona switch.

    Owns the summarization LLM call and the cache read/write against the
    chat context-summary table. If generation is unavailable, callers keep
    the original history so continuity is never replaced by a lossy fallback.

    A ``persona_boundary_summary_generator`` callable may be injected
    for unit tests; when set, it bypasses the LLM call entirely.
    """

    def __init__(
        self,
        *,
        chat_store: ChatStore | None,
        scenario_llm_pool: Any | None,
        llm_adapter: Any | None,
        persona_boundary_summary_generator: PersonaBoundarySummaryGenerator | None,
    ) -> None:
        self._chat_store = chat_store
        self._scenario_llm_pool = scenario_llm_pool
        self._llm_adapter = llm_adapter
        self._persona_boundary_summary_generator = persona_boundary_summary_generator

    # === public entry point ===

    async def summarize(
        self,
        *,
        session_id: str,
        history: list[Any],
        active_persona_id: str | None,
    ) -> tuple[list[Any], str | None]:
        """Return (history_tail, summary_text).

        ``history_tail`` is the active-persona segment (caller renders
        it normally into the prompt). ``summary_text`` is the neutral
        continuity blob (caller folds it into ``session_summary`` above
        the tail). Returns ``(history, None)`` when no persona switch
        is in scope (no active persona, empty history, no foreign
        persona in the prefix, etc.) — caller renders everything as-is.
        """
        normalized_persona_id = _normalize_persona_id(active_persona_id)
        if not normalized_persona_id or not history:
            return history, None
        boundary_index = self._find_persona_boundary_index(history, normalized_persona_id)
        if boundary_index is None or boundary_index <= 0:
            return history, None
        prefix = history[:boundary_index]
        if not self._history_has_foreign_persona(prefix, normalized_persona_id):
            return history, None
        tail = history[boundary_index:]
        try:
            summary_text = await self._get_or_create_summary(
                session_id=session_id,
                active_persona_id=normalized_persona_id,
                summarized_messages=prefix,
                retained_messages=tail,
            )
        except Exception:
            logger.exception(
                "Persona boundary summary failed; preserving original history session_id=%s",
                session_id,
            )
            return history, None
        if not summary_text:
            logger.warning(
                "Persona boundary summary unavailable; preserving original history session_id=%s",
                session_id,
            )
            return history, None
        return tail, summary_text

    # === summary cache + generation ===

    async def _get_or_create_summary(
        self,
        *,
        session_id: str,
        active_persona_id: str,
        summarized_messages: list[Any],
        retained_messages: list[Any],
    ) -> str | None:
        if not summarized_messages:
            return None
        first_kept_message_id = _message_id(retained_messages[0]) if retained_messages else None
        covered_from_message_id = _message_id(summarized_messages[0])
        covered_to_message_id = _message_id(summarized_messages[-1])
        if self._chat_store is not None:
            active_summary = await self._chat_store.get_active_context_summary(
                session_id=session_id,
                summary_kind=SUMMARY_KIND_PERSONA_BOUNDARY,
                persona_scope=active_persona_id,
            )
            if (
                active_summary is not None
                and active_summary.covered_to_message_id == covered_to_message_id
                and active_summary.first_kept_message_id == first_kept_message_id
                and active_summary.summary_text.strip()
            ):
                return active_summary.summary_text

        summary_input = PersonaBoundarySummaryInput(
            session_id=session_id,
            active_persona_id=active_persona_id,
            messages=self._build_messages(summarized_messages),
        )
        summary_text = await self._generate(summary_input)
        if self._chat_store is None or not summary_text:
            return summary_text or None

        now_ms = now_wall_ms()
        await self._chat_store.activate_context_summary(
            ChatContextSummaryRecord(
                summary_id=f"persona_boundary_{session_id}_{active_persona_id}_{now_ms}",
                session_id=session_id,
                parent_summary_id=None,
                status="active",
                summary_kind=SUMMARY_KIND_PERSONA_BOUNDARY,
                persona_scope=active_persona_id,
                covered_from_message_id=covered_from_message_id,
                covered_to_message_id=covered_to_message_id,
                first_kept_message_id=first_kept_message_id,
                covered_to_sequence_no=len(summarized_messages),
                session_origin="Previous transcript range before the current persona segment.",
                summary_text=summary_text,
                prompt_profile="persona_boundary",
                model_provider=self._resolve_model_provider(),
                model_id=self._resolve_model_id(),
                token_count_before=None,
                token_count_after=None,
                quality_status="generated",
                created_at_ms=now_ms,
                updated_at_ms=now_ms,
            )
        )
        return summary_text

    async def _generate(self, summary_input: PersonaBoundarySummaryInput) -> str:
        if self._persona_boundary_summary_generator is not None:
            generated = self._persona_boundary_summary_generator(summary_input)
            if inspect.isawaitable(generated):
                generated = await generated
            return str(generated or "").strip()
        summary_model = self._resolve_summary_model()
        if summary_model is None:
            return ""
        try:
            source_model = self._resolve_source_model()
            source_budget = build_context_window_budget(source_model.context)
            summary_model_budget = build_context_window_budget(summary_model.context)
            summary_output_tokens = resolve_cumulative_summary_output_tokens(
                resolve_summary_output_tokens(
                    source_budget,
                    summary_model_budget,
                    profile=PERSONA_SUMMARY_OUTPUT_PROFILE,
                ),
                input_capacity=summary_model_budget.input_capacity,
            )
            bridge = LLMProviderBridge(summary_model.adapter)
            system_prompt = _build_system_prompt(summary_output_tokens)

            async def _call_chunk(request: SummaryChunkRequest) -> str:
                response = await bridge.chat(
                    system_prompt=system_prompt,
                    messages=[{"role": "user", "content": request.prompt}],
                    max_tokens=summary_output_tokens,
                    temperature=0.2,
                    thinking_depth=ThinkingDepth.NONE,
                    event_context={
                        "request_kind": "memory:persona_boundary_summary",
                        "agent_id": "persona_boundary_summary",
                        "session_id": summary_input.session_id,
                        "chunk_index": request.index,
                        "chunk_final": request.is_final,
                    },
                )
                return str(response.content or "").strip()

            return await generate_cumulative_summary(
                source_text=_build_user_prompt(summary_input),
                system_prompt=system_prompt,
                input_capacity=summary_model_budget.input_capacity,
                build_prompt=_build_cumulative_prompt,
                call_chunk=_call_chunk,
            )
        except Exception:
            logger.exception(
                "Persona boundary summary generation failed session_id=%s",
                summary_input.session_id,
            )
            return ""

    # === adapter / model resolution ===

    def _resolve_scenario_model(self, scenario: LLMScenario) -> ResolvedModel | None:
        pool = self._scenario_llm_pool
        if pool is not None:
            resolver = getattr(pool, "resolve", None)
            if callable(resolver):
                try:
                    return resolver(scenario)
                except (ValueError, KeyError):
                    pass
            getter = getattr(pool, "get", None)
            if callable(getter):
                try:
                    adapter = getter(scenario)
                    return ResolvedModel(
                        adapter=adapter,
                        context=unknown_model_context(adapter),
                    )
                except (ValueError, KeyError):
                    pass
        return None

    def _resolve_summary_model(self) -> ResolvedModel | None:
        for scenario in (LLMScenario.CONTEXT_COMPACT, LLMScenario.CORE):
            resolved = self._resolve_scenario_model(scenario)
            if resolved is not None:
                return resolved
        if self._llm_adapter is None:
            return None
        return ResolvedModel(
            adapter=self._llm_adapter,
            context=unknown_model_context(self._llm_adapter),
        )

    def _resolve_source_model(self) -> ResolvedModel:
        resolved = self._resolve_scenario_model(LLMScenario.CORE)
        if resolved is not None:
            return resolved
        return ResolvedModel(
            adapter=self._llm_adapter,
            context=unknown_model_context(self._llm_adapter),
        )

    def _resolve_model_provider(self) -> str | None:
        resolved = self._resolve_summary_model()
        if resolved is None:
            return (
                "summary_generator"
                if self._persona_boundary_summary_generator is not None
                else None
            )
        return resolved.context.provider_id

    def _resolve_model_id(self) -> str | None:
        resolved = self._resolve_summary_model()
        if resolved is None:
            return (
                "persona_boundary_summary_generator"
                if self._persona_boundary_summary_generator is not None
                else None
            )
        return resolved.context.model_id

    # === history scanning ===

    @staticmethod
    def _find_persona_boundary_index(history: list[Any], active_persona_id: str) -> int | None:
        """Walk the transcript from the tail back; the boundary is the
        index *after* the last foreign-persona turn that precedes any
        current-persona turn. Returns None when no boundary exists."""
        saw_current_segment = False
        for index in range(len(history) - 1, -1, -1):
            persona_id = _message_persona_id(history[index])
            if persona_id == active_persona_id:
                saw_current_segment = True
                continue
            if not persona_id:
                continue
            if saw_current_segment:
                return index + 1
        if not saw_current_segment and any(
            persona_id and persona_id != active_persona_id
            for persona_id in (_message_persona_id(item) for item in history)
        ):
            return len(history)
        return None

    @staticmethod
    def _history_has_foreign_persona(history: list[Any], active_persona_id: str) -> bool:
        return any(
            persona_id and persona_id != active_persona_id
            for persona_id in (_message_persona_id(item) for item in history)
        )

    @staticmethod
    def _build_messages(history: list[Any]) -> list[PersonaBoundarySummaryMessage]:
        messages: list[PersonaBoundarySummaryMessage] = []
        for item in history:
            content = _message_content(item)
            if not content:
                continue
            messages.append(
                PersonaBoundarySummaryMessage(
                    message_id=_message_id(item),
                    role=str(getattr(item, "role", "") or "unknown").strip() or "unknown",
                    content=content,
                    persona_id=_message_persona_id(item),
                    message_kind=str(getattr(item, "message_kind", "") or "").strip() or None,
                )
            )
        return messages

# === LLM prompt builders (module-level so they remain pure / testable) ===


def _build_system_prompt(max_summary_tokens: int) -> str:
    return f"""You create neutral continuity summaries when a chat thread switches active assistant persona.

Rules:
- Preserve user requests, facts, decisions, constraints, commitments, unresolved tasks, and concrete artifacts.
- Do not imitate, quote, or preserve the previous persona's voice, style, jokes, self-reference, or emotional mannerisms.
- Refer to older assistant turns as previous assistant turns when attribution is needed.
- Write concise structured plain text that can be inserted into the next prompt.
- Keep the summary within {max_summary_tokens} tokens.
- Keep the current active persona authoritative for future replies.""".strip()


def _build_user_prompt(summary_input: PersonaBoundarySummaryInput) -> str:
    return "\n".join(
        [
            f"Session ID: {summary_input.session_id}",
            f"Current active persona ID: {summary_input.active_persona_id}",
            "",
            "Summarize the older transcript range below for continuity after a persona switch.",
            "Remove persona voice and preserve only task/content continuity.",
            "",
            "# Older Transcript Range",
            _render_messages(summary_input.messages),
            "",
            "Return the neutral continuity summary only.",
        ]
    ).strip()


def _build_cumulative_prompt(previous_summary: str, source_chunk: str) -> str:
    if not previous_summary:
        return source_chunk
    return (
        "Merge the previous neutral continuity summary with the next older transcript chunk. "
        "Return one cumulative neutral continuity summary only.\n\n"
        f"# Previous Partial Summary\n{previous_summary}\n\n"
        f"# Next Transcript Chunk\n{source_chunk}"
    )


def _render_messages(messages: list[PersonaBoundarySummaryMessage]) -> str:
    rendered: list[str] = []
    for message in messages:
        persona = message.persona_id or "none"
        message_id = message.message_id or "unknown"
        message_kind = message.message_kind or "unknown"
        rendered.append(
            f"[{message_id}] {message.role} persona={persona} kind={message_kind}:\n{message.content}"
        )
    return "\n\n".join(rendered)
