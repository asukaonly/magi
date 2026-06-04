"""History caches and explicit session validation for chat task agents."""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from magi.chat import ChatContextSummaryRecord, ChatStore
from magi.config.models import LLMScenario, ThinkingDepth
from magi.core.logger import get_logger
from magi.core.sqlite import connect_sqlite
from magi.llm.provider_bridge import LLMProviderBridge
from magi.utils.runtime import get_runtime_paths
from magi.agent.trace import now_wall_ms

from .tool_state_view import ChatToolStateView

logger = get_logger(__name__)

FACT_EVENTS_TABLE = "fact_events"
SUMMARY_KIND_PERSONA_BOUNDARY = "persona_boundary"
_PERSONA_BOUNDARY_OUTPUT_RESERVE = 4096
_PERSONA_BOUNDARY_CONTENT_LIMIT = 2400
_SESSION_ATTACHMENT_MANIFEST_LIMIT = 40


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


@dataclass(slots=True)
class CachedConversationHistory:
    """In-memory conversation history paired with the durable transcript version."""

    version: int
    messages: list[dict[str, Any]]
    session_summary: str | None = None
    session_origin: str | None = None
    active_persona_id: str | None = None
    loaded_at_ms: int = 0


class ChatHistoryService:
    """Owns history caches and lazy history loading for explicit sessions."""

    def __init__(
        self,
        *,
        l1_db_path: Path,
        runtime_trace_db_path: Optional[Path] = None,
        history_cache_max_sessions: int = 500,
        history_fetch_limit: int = 1000,
        chat_store: ChatStore | None = None,
        chat_read_service_factory: Callable[[], Any] | None = None,
        scenario_llm_pool: Any | None = None,
        llm_adapter: Any | None = None,
        persona_boundary_summary_generator: PersonaBoundarySummaryGenerator | None = None,
        conversation_log: Any | None = None,
    ) -> None:
        runtime_paths = get_runtime_paths()
        self._l1_db_path = l1_db_path
        self._runtime_trace_db_path = runtime_trace_db_path or runtime_paths.runtime_trace_db_path
        self._history_cache_max_sessions = history_cache_max_sessions
        self._history_fetch_limit = history_fetch_limit
        self._conversation_history: dict[str, CachedConversationHistory] = {}
        self._history_cache_order: list[str] = []
        # Recent tool interaction view used during prompt assembly.
        # Source of truth lives in ``runtime_trace``; this is a per-session
        # in-memory read view. Exposed as ``tool_state_view`` so the
        # chat task agent can pass it directly to postprocess + prompt
        # assembly without going through this class.
        self._tool_state_view = ChatToolStateView(
            runtime_trace_db_path=self._runtime_trace_db_path,
        )
        self._chat_store = chat_store
        self._chat_read_service_factory = chat_read_service_factory
        self._scenario_llm_pool = scenario_llm_pool
        self._llm_adapter = llm_adapter
        self._persona_boundary_summary_generator = persona_boundary_summary_generator
        # Phase F: optional typed-event view over the chat transcript. None
        # in test paths / pre-bootstrap; Task 8 will gate behavior on
        # presence rather than read-modify-write the legacy cache.
        self._conversation_log = conversation_log

    async def get_or_load_history(
        self,
        user_id: str,
        session_id: str,
        *,
        active_persona_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return (
            await self.get_or_load_history_context(
                user_id,
                session_id,
                active_persona_id=active_persona_id,
            )
        ).messages

    async def get_or_load_history_context(
        self,
        user_id: str,
        session_id: str,
        *,
        active_persona_id: str | None = None,
    ) -> CachedConversationHistory:
        history_key = self.history_key(user_id, session_id)
        normalized_persona_id = self._normalize_persona_id(active_persona_id)
        durable_version = 0
        active_summary = None
        if self._chat_store is not None:
            durable_version = await self._chat_store.get_history_version(session_id)
            active_summary = await self._chat_store.get_active_context_summary(session_id=session_id)
        cached_entry = self._conversation_history.get(history_key)
        if (
            cached_entry is not None
            and cached_entry.version == durable_version
            and cached_entry.active_persona_id == normalized_persona_id
        ):
            return cached_entry
        try:
            read_service = self._get_chat_read_service()
            history = read_service.get_conversation_history(
                user_id=user_id,
                session_id=session_id,
                limit=self._history_fetch_limit,
            )
            if active_summary is not None:
                history = self._filter_history_from_first_kept_message(
                    history,
                    first_kept_message_id=active_summary.first_kept_message_id,
                )
            history, persona_boundary_summary = await self._apply_persona_boundary_summary(
                session_id=session_id,
                history=history,
                active_persona_id=normalized_persona_id,
            )
            attachment_manifest = self._build_session_attachment_manifest(history)
            cached_history = CachedConversationHistory(
                version=durable_version,
                messages=[item.to_prompt_message() for item in history],
                session_summary=self._combine_session_summaries(
                    active_summary.summary_text if active_summary is not None else None,
                    persona_boundary_summary,
                    attachment_manifest,
                ),
                session_origin=(active_summary.session_origin if active_summary is not None else None),
                active_persona_id=normalized_persona_id,
            )
            self._conversation_history[history_key] = cached_history
            self._update_lru_cache(history_key)
            return cached_history
        except Exception as exc:
            logger.warning(
                "Failed to lazy load history | user=%s session=%s error=%s",
                user_id,
                session_id,
                exc,
            )
            if cached_entry is not None and cached_entry.active_persona_id == normalized_persona_id:
                return cached_entry
            return CachedConversationHistory(
                version=durable_version,
                messages=[],
                active_persona_id=normalized_persona_id,
            )

    def require_session_id(self, user_id: str, session_id: Optional[str] = None) -> str:
        _ = user_id
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            raise ValueError("Session ID is required")
        return normalized_session_id

    def history_key(self, user_id: str, session_id: str) -> str:
        return f"{user_id}::{session_id}"

    def get_history(self, user_id: str, session_id: str) -> list[dict[str, Any]]:
        cached = self._conversation_history.setdefault(
            self.history_key(user_id, session_id),
            CachedConversationHistory(version=0, messages=[]),
        )
        return cached.messages

    def append_user_message(self, history_key: str, user_message: str) -> None:
        if not user_message:
            return
        cached = self._conversation_history.setdefault(
            history_key,
            CachedConversationHistory(version=0, messages=[]),
        )
        history = cached.messages
        if history and history[-1].get("role") == "user" and history[-1].get("content") == user_message:
            return
        history.append({"role": "user", "content": user_message})
        self._update_lru_cache(history_key)
        # Phase F dual-write: PAUSED. The ConversationLog implementation writes
        # to the same chat_messages table that ChatOutcomeWriter (segmented /
        # final / interim) also writes to, producing duplicate rows that the
        # chat UI renders as ghost bubbles next to the real assistant message.
        # Reintroduce when ConversationLog gets its own event-only table that
        # doesn't compete with chat_messages — tracked for the cross-run
        # retract follow-up (Phase F+1).
        # if self._conversation_log is not None:
        #     self._fire_and_forget_log_append(
        #         history_key=history_key, event_type="user_message",
        #         actor=self._user_id_from_history_key(history_key), text=user_message,
        #     )

    def append_assistant_message(self, history_key: str, response_text: str) -> None:
        if not response_text:
            return
        cached = self._conversation_history.setdefault(
            history_key,
            CachedConversationHistory(version=0, messages=[]),
        )
        cached.messages.append({"role": "assistant", "content": response_text})
        self._update_lru_cache(history_key)
        # Phase F dual-write: PAUSED — see append_user_message above for why.

    @property
    def tool_state_view(self) -> ChatToolStateView:
        """Per-session recent-tool-call view shared with postprocess + prompt
        assembly. Callers should depend on this directly rather than going
        through ChatHistoryService."""
        return self._tool_state_view

    def get_conversation_history(self, user_id: str, session_id: str) -> list[dict[str, Any]]:
        active_session = self.require_session_id(user_id, session_id)
        cached = self._conversation_history.get(self.history_key(user_id, active_session))
        if cached is None:
            return []
        return cached.messages

    def get_cached_history_context(self, user_id: str, session_id: str) -> CachedConversationHistory | None:
        active_session = self.require_session_id(user_id, session_id)
        return self._conversation_history.get(self.history_key(user_id, active_session))

    def clear_conversation_history(self, user_id: str, session_id: str) -> None:
        active_session = self.require_session_id(user_id, session_id)
        key = self.history_key(user_id, active_session)
        current_version = self._conversation_history.get(key).version if key in self._conversation_history else 0
        self._conversation_history[key] = CachedConversationHistory(version=current_version, messages=[])
        self._tool_state_view.clear(key)

    def _update_lru_cache(self, history_key: str) -> None:
        if history_key in self._history_cache_order:
            self._history_cache_order.remove(history_key)
        self._history_cache_order.append(history_key)
        while len(self._history_cache_order) > self._history_cache_max_sessions:
            oldest_key = self._history_cache_order.pop(0)
            self._conversation_history.pop(oldest_key, None)
            self._tool_state_view.evict(oldest_key)
            logger.debug("Evicted history cache | key=%s", oldest_key)

    @staticmethod
    def _filter_history_from_first_kept_message(
        history: list[Any],
        *,
        first_kept_message_id: str | None,
    ) -> list[Any]:
        normalized_first_kept = str(first_kept_message_id or "").strip()
        if not normalized_first_kept:
            return history
        for index, item in enumerate(history):
            if str(getattr(item, "message_id", "") or "").strip() == normalized_first_kept:
                return history[index:]
        return history

    async def _apply_persona_boundary_summary(
        self,
        *,
        session_id: str,
        history: list[Any],
        active_persona_id: str | None,
    ) -> tuple[list[Any], str | None]:
        normalized_persona_id = self._normalize_persona_id(active_persona_id)
        if not normalized_persona_id or not history:
            return history, None
        boundary_index = self._find_persona_boundary_index(history, normalized_persona_id)
        if boundary_index is None or boundary_index <= 0:
            return history, None
        prefix = history[:boundary_index]
        if not self._history_has_foreign_persona(prefix, normalized_persona_id):
            return history, None
        tail = history[boundary_index:]
        summary_text = await self._get_or_create_persona_boundary_summary(
            session_id=session_id,
            active_persona_id=normalized_persona_id,
            summarized_messages=prefix,
            retained_messages=tail,
        )
        return tail, summary_text

    async def _get_or_create_persona_boundary_summary(
        self,
        *,
        session_id: str,
        active_persona_id: str,
        summarized_messages: list[Any],
        retained_messages: list[Any],
    ) -> str | None:
        if not summarized_messages:
            return None
        first_kept_message_id = self._message_id(retained_messages[0]) if retained_messages else None
        covered_from_message_id = self._message_id(summarized_messages[0])
        covered_to_message_id = self._message_id(summarized_messages[-1])
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
            messages=self._build_persona_boundary_messages(summarized_messages),
        )
        summary_text = await self._generate_persona_boundary_summary(summary_input)
        if not summary_text:
            summary_text = self._build_persona_boundary_fallback(summary_input)
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

    async def _generate_persona_boundary_summary(
        self,
        summary_input: PersonaBoundarySummaryInput,
    ) -> str:
        if self._persona_boundary_summary_generator is not None:
            generated = self._persona_boundary_summary_generator(summary_input)
            if inspect.isawaitable(generated):
                generated = await generated
            return str(generated or "").strip()
        adapter = self._resolve_summary_adapter()
        if adapter is None:
            return ""
        try:
            bridge = LLMProviderBridge(adapter)
            response = await bridge.chat(
                system_prompt=self._build_persona_boundary_system_prompt(),
                messages=[{"role": "user", "content": self._build_persona_boundary_user_prompt(summary_input)}],
                max_tokens=_PERSONA_BOUNDARY_OUTPUT_RESERVE,
                temperature=0.2,
                thinking_depth=ThinkingDepth.NONE,
                event_context={
                    "request_kind": "memory:persona_boundary_summary",
                    "agent_id": "persona_boundary_summary",
                    "session_id": summary_input.session_id,
                },
            )
            return str(response.content or "").strip()
        except Exception:
            logger.exception("Persona boundary summary generation failed session_id=%s", summary_input.session_id)
            return ""

    def _resolve_summary_adapter(self) -> Any | None:
        if self._scenario_llm_pool is not None:
            try:
                return self._scenario_llm_pool.get(LLMScenario.CONTEXT_COMPACT)
            except (ValueError, KeyError):
                try:
                    return self._scenario_llm_pool.get(LLMScenario.CORE)
                except (ValueError, KeyError):
                    return None
        return self._llm_adapter

    def _resolve_model_provider(self) -> str | None:
        adapter = self._resolve_summary_adapter()
        if adapter is None:
            return "summary_generator" if self._persona_boundary_summary_generator is not None else None
        provider = getattr(adapter, "provider", None) or getattr(adapter, "provider_name", None)
        return str(provider) if provider is not None else None

    def _resolve_model_id(self) -> str | None:
        adapter = self._resolve_summary_adapter()
        if adapter is None:
            return "persona_boundary_summary_generator" if self._persona_boundary_summary_generator is not None else None
        model_id = getattr(adapter, "model_id", None) or getattr(adapter, "model_name", None)
        return str(model_id) if model_id is not None else None

    @staticmethod
    def _find_persona_boundary_index(history: list[Any], active_persona_id: str) -> int | None:
        saw_current_segment = False
        for index in range(len(history) - 1, -1, -1):
            persona_id = ChatHistoryService._message_persona_id(history[index])
            if persona_id == active_persona_id:
                saw_current_segment = True
                continue
            if not persona_id:
                continue
            if saw_current_segment:
                return index + 1
        if not saw_current_segment and any(
            persona_id and persona_id != active_persona_id
            for persona_id in (ChatHistoryService._message_persona_id(item) for item in history)
        ):
            return len(history)
        return None

    @staticmethod
    def _history_has_foreign_persona(history: list[Any], active_persona_id: str) -> bool:
        return any(
            persona_id and persona_id != active_persona_id
            for persona_id in (ChatHistoryService._message_persona_id(item) for item in history)
        )

    @staticmethod
    def _build_persona_boundary_messages(history: list[Any]) -> list[PersonaBoundarySummaryMessage]:
        messages: list[PersonaBoundarySummaryMessage] = []
        for item in history:
            content = str(getattr(item, "content", "") or "").strip()
            if not content:
                continue
            if len(content) > _PERSONA_BOUNDARY_CONTENT_LIMIT:
                content = content[:_PERSONA_BOUNDARY_CONTENT_LIMIT].rstrip() + "\n... [truncated]"
            messages.append(
                PersonaBoundarySummaryMessage(
                    message_id=ChatHistoryService._message_id(item),
                    role=str(getattr(item, "role", "") or "unknown").strip() or "unknown",
                    content=content,
                    persona_id=ChatHistoryService._message_persona_id(item),
                    message_kind=str(getattr(item, "message_kind", "") or "").strip() or None,
                )
            )
        return messages

    @staticmethod
    def _build_persona_boundary_system_prompt() -> str:
        return """You create neutral continuity summaries when a chat thread switches active assistant persona.

Rules:
- Preserve user requests, facts, decisions, constraints, commitments, unresolved tasks, and concrete artifacts.
- Do not imitate, quote, or preserve the previous persona's voice, style, jokes, self-reference, or emotional mannerisms.
- Refer to older assistant turns as previous assistant turns when attribution is needed.
- Write concise structured plain text that can be inserted into the next prompt.
- Keep the current active persona authoritative for future replies.""".strip()

    @staticmethod
    def _build_persona_boundary_user_prompt(summary_input: PersonaBoundarySummaryInput) -> str:
        return "\n".join(
            [
                f"Session ID: {summary_input.session_id}",
                f"Current active persona ID: {summary_input.active_persona_id}",
                "",
                "Summarize the older transcript range below for continuity after a persona switch.",
                "Remove persona voice and preserve only task/content continuity.",
                "",
                "# Older Transcript Range",
                ChatHistoryService._render_persona_boundary_messages(summary_input.messages),
                "",
                "Return the neutral continuity summary only.",
            ]
        ).strip()

    @staticmethod
    def _render_persona_boundary_messages(messages: list[PersonaBoundarySummaryMessage]) -> str:
        rendered: list[str] = []
        for message in messages:
            persona = message.persona_id or "none"
            message_id = message.message_id or "unknown"
            message_kind = message.message_kind or "unknown"
            rendered.append(
                f"[{message_id}] {message.role} persona={persona} kind={message_kind}:\n{message.content}"
            )
        return "\n\n".join(rendered)

    @staticmethod
    def _build_persona_boundary_fallback(summary_input: PersonaBoundarySummaryInput) -> str:
        lines = [
            "Previous transcript range before the current active persona segment:",
        ]
        for message in summary_input.messages[:24]:
            content = message.content.replace("\n", " ").strip()
            if len(content) > 320:
                content = content[:320].rstrip() + "..."
            if message.role == "user":
                lines.append(f"- User request/context: {content}")
            elif message.persona_id and message.persona_id != summary_input.active_persona_id:
                lines.append(f"- Previous assistant turn content, neutralized for continuity: {content}")
            else:
                lines.append(f"- Prior {message.role} context: {content}")
        if len(summary_input.messages) > 24:
            lines.append(f"- {len(summary_input.messages) - 24} additional older messages were omitted from fallback detail.")
        return "\n".join(lines).strip()

    @staticmethod
    def _combine_session_summaries(
        token_budget_summary: str | None,
        persona_boundary_summary: str | None,
        attachment_manifest: str | None = None,
    ) -> str | None:
        token_text = str(token_budget_summary or "").strip()
        boundary_text = str(persona_boundary_summary or "").strip()
        attachment_text = str(attachment_manifest or "").strip()
        sections: list[str] = []
        if token_text:
            sections.extend(["# Rolling Token-Budget Summary", token_text, ""])
        if boundary_text:
            sections.extend(["# Persona Boundary Summary", boundary_text, ""])
        if attachment_text:
            sections.extend(["# Session Attachment References", attachment_text])
        return "\n".join(sections).strip() or None

    @staticmethod
    def _build_session_attachment_manifest(messages: list[Any]) -> str | None:
        all_entries: list[str] = []
        for message in messages:
            attachments = getattr(message, "attachments", None)
            if not isinstance(attachments, list):
                continue
            for attachment in attachments:
                if not isinstance(attachment, dict):
                    continue
                attachment_id = str(attachment.get("attachment_id") or "").strip()
                if not attachment_id:
                    continue
                name = str(attachment.get("original_name") or "attachment").strip() or "attachment"
                kind = str(attachment.get("kind") or "file").strip() or "file"
                details = [
                    f"attachment_id={attachment_id}",
                    f"name={name}",
                    f"kind={kind}",
                ]
                page_count = attachment.get("page_count")
                if isinstance(page_count, int):
                    details.append(f"pages={page_count}")
                character_count = attachment.get("character_count")
                if isinstance(character_count, int):
                    details.append(f"chars={character_count}")
                parse_status = str(attachment.get("parse_status") or "").strip()
                if parse_status:
                    details.append(f"parse_status={parse_status}")
                turn_id = str(getattr(message, "turn_id", "") or "").strip()
                if turn_id:
                    details.append(f"turn_id={turn_id}")
                all_entries.append("- " + "; ".join(details))
        if not all_entries:
            return None
        omitted = max(0, len(all_entries) - _SESSION_ATTACHMENT_MANIFEST_LIMIT)
        entries = all_entries[-_SESSION_ATTACHMENT_MANIFEST_LIMIT:]
        lines = [
            "These are lightweight references to files attached in this session.",
            "Use `read_chat_attachment` with an `attachment_id` when the user asks about an earlier attachment; do not guess attachment contents from memory.",
            *entries,
        ]
        if omitted:
            lines.append(f"- {omitted} older attachment reference(s) omitted from this prompt manifest.")
        return "\n".join(lines).strip()

    @staticmethod
    def _message_persona_id(item: Any) -> str | None:
        return ChatHistoryService._normalize_persona_id(getattr(item, "persona_id", None))

    @staticmethod
    def _message_id(item: Any) -> str | None:
        return str(getattr(item, "message_id", "") or "").strip() or None

    @staticmethod
    def _normalize_persona_id(persona_id: str | None) -> str | None:
        return str(persona_id or "").strip() or None

    def _get_chat_read_service(self):  # type: ignore[no-untyped-def]
        if self._chat_read_service_factory is not None:
            read_service = self._chat_read_service_factory()
        else:
            from magi.chat.read_service import get_chat_read_service

            read_service = get_chat_read_service()
        if self._chat_store is not None and hasattr(read_service, "_chat_db_path"):
            current_path = Path(getattr(read_service, "_chat_db_path"))
            target_path = Path(self._chat_store.db_path)
            if current_path != target_path:
                close = getattr(read_service, "close", None)
                if callable(close):
                    close()
                setattr(read_service, "_chat_db_path", target_path)
        return read_service

    def restore_conversation_from_events(self) -> None:
        fact_rows: list[tuple[Any, ...]] = []
        try:
            if not self._l1_db_path.exists():
                return
            conn = connect_sqlite(self._l1_db_path, profile="hot_write", use_row_factory=False)
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT event_type, content, timestamp, user_id, session_id, turn_id
                FROM {FACT_EVENTS_TABLE}
                WHERE deleted_at IS NULL
                  AND event_type IN ('UserMessage', 'AIResponse')
                ORDER BY timestamp ASC
                LIMIT 5000
                """
            )
            fact_rows = cur.fetchall()
            conn.close()
        except Exception as exc:
            logger.warning("Failed to restore conversation from L1 store: %s", exc)
            return

        for event_type, raw_content, _, user_id, raw_session_id, _ in fact_rows:
            if not user_id:
                continue
            session_id = str(raw_session_id or "").strip()
            if not session_id:
                continue
            key = self.history_key(user_id, session_id)
            cached = self._conversation_history.setdefault(
                key,
                CachedConversationHistory(version=0, messages=[]),
            )
            history = cached.messages
            if event_type == "UserMessage":
                content = str(raw_content or "").strip()
                if content:
                    history.append({"role": "user", "content": str(content)})
            elif event_type == "AIResponse":
                content = str(raw_content or "").strip()
                if content:
                    history.append({"role": "assistant", "content": str(content)})

        self._tool_state_view.restore_from_trace(
            require_session_id=self.require_session_id,
            build_history_key=self.history_key,
        )

    @staticmethod
    def _user_id_from_history_key(history_key: str) -> str:
        """history_key format is ``user_id::session_id``."""
        parts = history_key.split("::", 1)
        return parts[0] if parts else ""

    @staticmethod
    def _session_id_from_history_key(history_key: str) -> str:
        parts = history_key.split("::", 1)
        return parts[1] if len(parts) > 1 else ""

    def _fire_and_forget_log_append(
        self,
        *,
        history_key: str,
        event_type: str,
        actor: str,
        text: str,
    ) -> None:
        """Schedule an async append to ConversationLog without blocking the
        caller. Errors are logged and swallowed — a failed dual-write must
        never break the in-memory cache mutation that already happened."""
        log = self._conversation_log
        if log is None:
            return
        import asyncio as _asyncio
        import time as _time
        import uuid as _uuid

        from magi_plugin_sdk.conversation import ContentBlock, ConversationEvent

        session_id = self._session_id_from_history_key(history_key)
        if not session_id:
            return
        try:
            event = ConversationEvent(
                event_id=_uuid.uuid4().hex,
                event_type=event_type,
                timestamp_ms=int(_time.time() * 1000),
                actor=actor,
                content=[ContentBlock(kind="text", text=text)],
            )
        except Exception:
            logger.warning(
                "ConversationLog dual-write: event construction failed", exc_info=True
            )
            return
        try:
            loop = _asyncio.get_event_loop()
        except RuntimeError:
            # No event loop bound to this thread — skip silently (sync init path).
            return
        if not loop.is_running():
            # Sync context (e.g. test setup outside pytest-asyncio) — skip.
            return
        try:
            loop.create_task(log.append(event, session_id=session_id))
        except Exception:
            logger.warning(
                "ConversationLog dual-write: scheduling failed", exc_info=True
            )
