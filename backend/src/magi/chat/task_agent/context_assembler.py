"""History caches and explicit session validation for chat task agents."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from magi.chat import ChatStore
from magi.core.logger import get_logger
from magi.core.sqlite import connect_sqlite
from magi.utils.runtime import get_runtime_paths

from .persona_boundary import (
    PersonaBoundarySummarizer,
    PersonaBoundarySummaryGenerator,
)
from .tool_state_view import ChatToolStateView

logger = get_logger(__name__)

FACT_EVENTS_TABLE = "fact_events"
_SESSION_ATTACHMENT_MANIFEST_LIMIT = 40


@dataclass(slots=True)
class CachedConversationHistory:
    """In-memory conversation history paired with the durable transcript version."""

    version: int
    messages: list[dict[str, Any]]
    session_summary: str | None = None
    session_origin: str | None = None
    active_persona_id: str | None = None
    loaded_at_ms: int = 0


class ChatContextAssembler:
    """Owns history caches and lazy history loading for explicit sessions."""

    def __init__(
        self,
        *,
        l1_db_path: Path,
        runtime_trace_db_path: Optional[Path] = None,
        history_cache_max_sessions: int = 500,
        chat_store: ChatStore | None = None,
        chat_read_service_factory: Callable[[], Any] | None = None,
        scenario_llm_pool: Any | None = None,
        llm_adapter: Any | None = None,
        persona_boundary_summary_generator: PersonaBoundarySummaryGenerator | None = None,
    ) -> None:
        runtime_paths = get_runtime_paths()
        self._l1_db_path = l1_db_path
        self._runtime_trace_db_path = runtime_trace_db_path or runtime_paths.runtime_trace_db_path
        self._history_cache_max_sessions = history_cache_max_sessions
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
        # Persona-boundary continuity summarizer. Owns the LLM call +
        # the chat_context_summaries cache; called once per turn from
        # ``get_or_load_history_context``. See persona_boundary.py for
        # the layering rationale (kept local to chat until another driver
        # needs it).
        self._persona_boundary = PersonaBoundarySummarizer(
            chat_store=chat_store,
            scenario_llm_pool=scenario_llm_pool,
            llm_adapter=llm_adapter,
            persona_boundary_summary_generator=persona_boundary_summary_generator,
        )

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
            first_kept_message_id = (
                active_summary.first_kept_message_id if active_summary is not None else None
            )
            history = read_service.get_conversation_history(
                user_id=user_id,
                session_id=session_id,
                limit=None,
                start_message_id=first_kept_message_id,
            )
            attachment_manifest = self._build_attachment_manifest_from_references(
                read_service.get_session_attachment_references(
                    user_id=user_id,
                    session_id=session_id,
                    limit=_SESSION_ATTACHMENT_MANIFEST_LIMIT,
                )
            )
            history, persona_boundary_summary = await self._persona_boundary.summarize(
                session_id=session_id,
                history=history,
                active_persona_id=normalized_persona_id,
            )
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
        """Push a user message onto the in-memory LLM-prompt cache.

        Does *not* persist to chat_messages — the durable write happens
        elsewhere (dispatcher for user messages; ChatOutcomeWriter for
        assistant replies; ControlTranscriptSubscriber for plan/todo/ask
        control state). This call only keeps the prompt cache hot so the
        next LLM turn does not need to re-query the DB.
        """
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

    def append_assistant_message(self, history_key: str, response_text: str) -> None:
        """Push an assistant reply onto the in-memory LLM-prompt cache.

        Cache-only (see :py:meth:`append_user_message` for the durable
        write path).
        """
        if not response_text:
            return
        cached = self._conversation_history.setdefault(
            history_key,
            CachedConversationHistory(version=0, messages=[]),
        )
        cached.messages.append({"role": "assistant", "content": response_text})
        self._update_lru_cache(history_key)

    @property
    def tool_state_view(self) -> ChatToolStateView:
        """Per-session recent-tool-call view shared with postprocess + prompt
        assembly. Callers should depend on this directly rather than going
        through ChatContextAssembler."""
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
        references: list[dict[str, Any]] = []
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
                reference = dict(attachment)
                turn_id = str(getattr(message, "turn_id", "") or "").strip()
                if turn_id:
                    reference["turn_id"] = turn_id
                references.append(reference)
        return ChatContextAssembler._build_attachment_manifest_from_references(references)

    @staticmethod
    def _build_attachment_manifest_from_references(
        references: list[dict[str, Any]],
    ) -> str | None:
        all_entries: list[str] = []
        for attachment in references:
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
            turn_id = str(attachment.get("turn_id") or "").strip()
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
    def _normalize_persona_id(persona_id: str | None) -> str | None:
        # Still needed by ``get_or_load_history_context`` to keep cache
        # entries comparable across calls. The ``_message_id`` /
        # ``_message_persona_id`` helpers moved into
        # ``persona_boundary.py`` since only the summarizer used them.
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
