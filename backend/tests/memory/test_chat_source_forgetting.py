from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
import pytest

from _shared.memory_schema import apply_memory_shared_schema
from magi.chat.asset_gc import ChatAssetGC
from magi.chat.assistant_memory_projection import (
    ChatAssistantMemoryProjectionService,
)
from magi.chat.memory_projection_clear import ChatMemoryProjectionClearLifecycle
from magi.chat.forgetting import ChatForgettingService, ChatSurfaceFinalizer
from magi.chat.read_service import ChatReadService
from magi.chat.store import ChatStore
from magi.chat.storage.schema import CHAT_STORE_SCHEMA_SQL
from magi.chat.task_agent.context_assembler import ChatContextAssembler
from magi.db.migrations.runtime_trace.versions.v1_initial import (
    SCHEMA_SQL as RUNTIME_TRACE_SCHEMA_SQL,
)
from magi.memory.event_contracts import (
    IngestTarget,
    MemoryDomain,
    MemoryEvent,
    RetentionClass,
    TomDepth,
)
from magi.memory.l0.attention import (
    AttentionActionType,
    AttentionKind,
    AttentionUpdateAction,
)
from magi.memory.l3.models import L3Candidate
from magi.memory.source_event_governance import (
    business_source_references,
    chat_session_source_reference,
    memory_event_source_references,
)
from magi.memory.unified_store import MemoryStoreTuning, UnifiedMemoryStore
from magi.utils.runtime import RuntimePaths


def test_business_source_references_match_owner_and_idempotency_scopes() -> None:
    user_message = business_source_references(
        source="chat",
        event_type="UserMessage",
        source_item_id="message-1",
        idempotency_key="shared-key",
    )
    assistant_message = business_source_references(
        source="chat",
        event_type="AIResponse",
        source_item_id="message-1",
        idempotency_key="shared-key",
    )
    case_distinct_source = business_source_references(
        source="Chat",
        event_type="UserMessage",
        source_item_id="message-1",
        idempotency_key="shared-key",
    )

    assert user_message[0] == assistant_message[0]
    assert user_message[1] != assistant_message[1]
    assert set(user_message).isdisjoint(case_distinct_source)


def test_runtime_session_without_user_keeps_event_scoped_references() -> None:
    event = MemoryEvent(
        event_id="event-runtime",
        correlation_id="correlation-runtime",
        timestamp=1_720_000_000.0,
        created_at=1_720_000_000.0,
        event_type="ActionExecuted",
        source="persona_generation",
        source_item_id=None,
        memory_domain=MemoryDomain.RUNTIME_TELEMETRY,
        ingest_target=IngestTarget.RUNTIME_ONLY,
        cognition_eligible=False,
        tom_depth=TomDepth.NONE,
        retention_class=RetentionClass.DISPOSABLE,
        session_id="persona_generation",
        turn_id="turn-runtime",
        user_id=None,
        task_id=None,
        content="web-search",
        author_type="tool",
        content_type="tool_result",
        importance_score=0.1,
        level=20,
        idempotency_key=None,
    )

    assert memory_event_source_references(event) == (
        "event-runtime",
        "turn-runtime",
    )


def _memory_event(
    event_id: str,
    *,
    session_id: str,
    turn_id: str,
    content: str,
    message_id: str | None = None,
    author_type: str = "user",
    created_at: float = 1_720_000_000.0,
) -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        correlation_id=f"correlation:{event_id}",
        timestamp=1_720_000_000.0,
        created_at=created_at,
        event_type="AIResponse" if author_type == "assistant" else "UserMessage",
        source="chat",
        source_item_id=message_id,
        memory_domain=MemoryDomain.USER_AUTHORED,
        ingest_target=IngestTarget.L1_ONLY,
        cognition_eligible=True,
        tom_depth=TomDepth.NONE,
        retention_class=RetentionClass.PERMANENT,
        session_id=session_id,
        turn_id=turn_id,
        user_id="u1",
        task_id=None,
        content=content,
        author_type=author_type,
        content_type="text",
        importance_score=0.9,
        level=20,
        idempotency_key=message_id,
    )


async def _build_memory(
    tmp_path: Path,
    *,
    initialize_schema: bool = True,
) -> UnifiedMemoryStore:
    memory_db = tmp_path / "memory.db"
    if initialize_schema:
        await apply_memory_shared_schema(str(memory_db))
    memory = UnifiedMemoryStore(
        persist_dir=str(tmp_path / "memory"),
        l1_db_path=str(tmp_path / "l1.db"),
        memory_db_path=str(memory_db),
        l2_batch_flush_interval_seconds=0,
        tuning=MemoryStoreTuning(
            enable_l1_vectors=False,
            enable_l2_vectors=False,
            enable_l3_vectors=False,
            enable_l4_vectors=False,
            enable_l3_llm_summary=False,
            async_embeddings=False,
        ),
    )
    await memory.initialize()
    return memory


def _attention_action(
    *,
    summary: str,
    kind: AttentionKind = AttentionKind.FOCUS,
    source_turn_ids: tuple[str, ...] = (),
    source_event_ids: tuple[str, ...] = (),
    entity_id: str | None = None,
) -> AttentionUpdateAction:
    return AttentionUpdateAction(
        action=AttentionActionType.ADD,
        kind=kind,
        summary=summary,
        salience=0.8,
        confidence=0.9,
        source_turn_ids=source_turn_ids,
        source_event_ids=source_event_ids,
        entity_id=entity_id,
    )


async def _apply_attention(
    memory: UnifiedMemoryStore,
    *,
    session_id: str,
    actions: list[AttentionUpdateAction],
    last_processed_turn_id: str,
) -> None:
    assert memory.l0 is not None
    snapshot = await memory.l0.get_attention_snapshot(session_id)
    result = await memory.l0.apply_attention_actions(
        session_id=session_id,
        actions=actions,
        expected_revision=int(snapshot["revision"]),
        last_processed_turn_id=last_processed_turn_id,
    )
    assert result is not None


class _DirectReadAdapter:
    def __init__(self, service: ChatReadService) -> None:
        self._service = service

    async def aget_session_summary(self, user_id: str, session_id: str):
        return self._service.get_session_summary(user_id, session_id)

    async def alist_session_turn_ids(self, user_id: str, session_id: str) -> list[str]:
        return self._service.list_session_turn_ids(user_id, session_id)

    async def aget_message_source_identity(
        self,
        user_id: str,
        session_id: str,
        message_id: str,
    ):
        return self._service.get_message_source_identity(user_id, session_id, message_id)

    async def alist_message_replacement_source_identities(
        self,
        user_id: str,
        session_id: str,
        message_id: str,
    ):
        return self._service.list_message_replacement_source_identities(
            user_id,
            session_id,
            message_id,
        )

    async def alist_session_message_source_identities(
        self,
        user_id: str,
        session_id: str,
    ):
        return self._service.list_session_message_source_identities(user_id, session_id)

    async def aclear_conversation_history_snapshot(
        self,
        user_id: str,
        session_id: str,
        message_ids: list[str],
        turn_ids: list[str],
    ) -> None:
        self._service.clear_conversation_history_snapshot(
            user_id,
            session_id,
            message_ids,
            turn_ids,
        )

    async def adelete_session(self, user_id: str, session_id: str) -> None:
        self._service.delete_session(user_id, session_id)

    async def aforget_message_artifacts(
        self,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> bool:
        return self._service.forget_message_artifacts(user_id, session_id, message_id)


class _UnusedSurfaceWriter:
    async def hide_message(self, **_kwargs) -> bool:  # type: ignore[no-untyped-def]
        raise AssertionError("message hiding is not part of session deletion")


class _NoopRuntimeForgettingCoordinator:
    @asynccontextmanager
    async def forget_operation_boundary(self):
        yield

    @asynccontextmanager
    async def background_scope_boundary(self, **_scope):  # type: ignore[no-untyped-def]
        yield

    async def prepare_session_delete(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> object:
        return object()

    async def prepare_message_delete(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
        message_id: str,
        include_turn_scope: bool,
        run_id: str | None,
        run_revision: int,
        runtime_turn_ids: list[str],
        replay_turn_ids: list[str],
        related_message_ids: list[str] | None = None,
        background_task_ids: list[str] | None = None,
    ) -> object:
        return object()

    @asynccontextmanager
    async def message_delete_boundary(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
        message_id: str,
        include_turn_scope: bool,
        run_id: str | None,
        run_revision: int,
        runtime_turn_ids: list[str],
        replay_turn_ids: list[str],
        related_message_ids: list[str],
        background_task_ids: list[str],
        prepare_intent,
    ):
        _ = (
            user_id,
            session_id,
            turn_id,
            message_id,
            include_turn_scope,
            run_id,
            run_revision,
            replay_turn_ids,
            background_task_ids,
            related_message_ids,
        )
        await prepare_intent(runtime_turn_ids, replay_turn_ids)
        yield object()

    async def quiesce_history_clear(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> object:
        return object()

    async def prepare_history_clear(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_ids: list[str],
        message_ids: list[str],
    ) -> object:
        return object()


class _CrashAfterMemoryReadAdapter(_DirectReadAdapter):
    def __init__(self, service: ChatReadService, *, operation: str) -> None:
        super().__init__(service)
        self._operation = operation

    async def adelete_session(self, user_id: str, session_id: str) -> None:
        if self._operation == "chat_session":
            raise RuntimeError("simulated surface crash")
        await super().adelete_session(user_id, session_id)

    async def aforget_message_artifacts(
        self,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> bool:
        if self._operation == "chat_message":
            raise RuntimeError("simulated surface crash")
        return await super().aforget_message_artifacts(user_id, session_id, message_id)

    async def aclear_conversation_history_snapshot(
        self,
        user_id: str,
        session_id: str,
        message_ids: list[str],
        turn_ids: list[str],
    ) -> None:
        if self._operation == "chat_history":
            raise RuntimeError("simulated surface crash")
        await super().aclear_conversation_history_snapshot(
            user_id,
            session_id,
            message_ids,
            turn_ids,
        )


class _DirectSurfaceWriter:
    def __init__(self, chat_db: Path) -> None:
        self._chat_db = chat_db

    async def hide_message(
        self,
        *,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> bool:
        conn = sqlite3.connect(self._chat_db)
        try:
            cursor = conn.execute(
                """
                UPDATE chat_messages
                SET is_visible = 0
                WHERE user_id = ? AND session_id = ? AND message_id = ?
                  AND is_visible = 1
                """,
                (user_id, session_id, message_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()


def _seed_chat_session(chat_db: Path) -> None:
    conn = sqlite3.connect(chat_db)
    conn.executescript(CHAT_STORE_SCHEMA_SQL)
    conn.execute("""
        INSERT INTO chat_sessions(
            session_id, user_id, title, title_overridden, summary,
            created_at_ms, updated_at_ms, last_message_preview,
            last_user_message_preview, message_count, history_version
        ) VALUES ('session-1', 'u1', 'Private', 0, '', 1, 1, 'private', 'private', 1, 0)
        """)
    conn.execute("""
        INSERT INTO chat_turns(
            turn_id, session_id, user_id, status, response_mode,
            ux_plan_json, created_at_ms, updated_at_ms, run_revision
        ) VALUES ('turn-1', 'session-1', 'u1', 'completed', 'final_only', '{}', 1, 1, 0)
        """)
    conn.execute("""
        INSERT INTO chat_messages(
            message_id, session_id, turn_id, user_id, role, message_kind,
            content_text, payload_json, is_final, is_visible, created_at_ms, sequence_no
        ) VALUES (
            'message-1', 'session-1', 'turn-1', 'u1', 'user', 'user_text',
            'private content', '{}', 1, 1, 1, 1
        )
        """)
    conn.commit()
    conn.close()


def _seed_chat_turn_with_two_messages(chat_db: Path) -> None:
    _seed_chat_session(chat_db)
    conn = sqlite3.connect(chat_db)
    conn.execute("""
        INSERT INTO chat_messages(
            message_id, session_id, turn_id, user_id, role, message_kind,
            content_text, payload_json, is_final, is_visible, created_at_ms, sequence_no
        ) VALUES (
            'message-assistant', 'session-1', 'turn-1', 'u1', 'assistant',
            'assistant_final', 'assistant content', '{}', 1, 1, 2, 2
        )
        """)
    conn.execute("""
        UPDATE chat_sessions
        SET message_count = 2, history_version = 2
        WHERE session_id = 'session-1'
        """)
    conn.commit()
    conn.close()


def _seed_chat_turn_with_rhythm_segments(chat_db: Path) -> None:
    _seed_chat_session(chat_db)
    conn = sqlite3.connect(chat_db)
    for index in range(3):
        conn.execute(
            """
            INSERT INTO chat_messages(
                message_id, session_id, turn_id, user_id, role, message_kind,
                content_text, payload_json, is_final, is_visible, created_at_ms,
                sequence_no
            ) VALUES (?, 'session-1', 'turn-1', 'u1', 'assistant',
                      'assistant_rhythm_segment', ?, ?, 1, 1, ?, ?)
            """,
            (
                f"rhythm-{index + 1}",
                f"part {index + 1}",
                json.dumps(
                    {
                        "rhythm": {
                            "segment_index": index,
                            "segment_count": 3,
                        }
                    }
                ),
                index + 2,
                index + 2,
            ),
        )
    conn.execute(
        """
        UPDATE chat_sessions
        SET message_count = 4, history_version = 4
        WHERE session_id = 'session-1'
        """
    )
    conn.commit()
    conn.close()


def _seed_new_message_after_crash(chat_db: Path) -> None:
    conn = sqlite3.connect(chat_db)
    conn.execute("""
        INSERT INTO chat_turns(
            turn_id, session_id, user_id, status, response_mode,
            ux_plan_json, created_at_ms, updated_at_ms, run_revision
        ) VALUES (
            'turn-after-crash', 'session-1', 'u1', 'completed',
            'final_only', '{}', 10, 10, 0
        )
        """)
    conn.execute("""
        INSERT INTO chat_messages(
            message_id, session_id, turn_id, user_id, role, message_kind,
            content_text, payload_json, is_final, is_visible, created_at_ms,
            sequence_no
        ) VALUES (
            'message-after-crash', 'session-1', 'turn-after-crash', 'u1',
            'user', 'user_text', 'new content must survive', '{}', 1, 1, 10, 1
        )
        """)
    conn.execute("""
        UPDATE chat_sessions
        SET last_message_preview = 'new content must survive',
            last_user_message_preview = 'new content must survive',
            message_count = 2,
            updated_at_ms = 10
        WHERE session_id = 'session-1'
        """)
    conn.commit()
    conn.close()


def _seed_message_artifacts(
    *,
    chat_db: Path,
    runtime_paths: RuntimePaths,
) -> tuple[Path, Path, Path]:
    attachment_path = (
        runtime_paths.chat_files_dir / "session-1" / "turn-1" / "attachment-private.txt"
    )
    attachment_path.parent.mkdir(parents=True, exist_ok=True)
    attachment_path.write_text("assistant content", encoding="utf-8")
    relative_attachment_path = attachment_path.relative_to(runtime_paths.base_dir).as_posix()
    derived_path = runtime_paths.chat_derived_dir / "session-1" / "turn-1" / "attachment-1.txt"
    derived_path.parent.mkdir(parents=True, exist_ok=True)
    derived_path.write_text("assistant content", encoding="utf-8")

    conn = sqlite3.connect(chat_db)
    conn.execute(
        """
        UPDATE chat_messages
        SET payload_json = ?,
            label_json = '{"private":"assistant content"}',
            reply_to_message_id = 'message-1'
        WHERE message_id = 'message-assistant'
        """,
        (
            json.dumps(
                {
                    "attachments": [
                        {
                            "attachment_id": "attachment-1",
                            "storage_path": str(attachment_path),
                            "derived_text_path": str(derived_path),
                        }
                    ]
                }
            ),
        ),
    )
    conn.execute("""
        INSERT INTO chat_messages(
            message_id, session_id, turn_id, user_id, role, message_kind,
            content_text, payload_json, is_final, is_visible, created_at_ms,
            sequence_no, reply_to_message_id
        ) VALUES (
            'message-reply', 'session-1', 'turn-1', 'u1', 'assistant',
            'assistant_final', 'kept reply', '{}', 1, 1, 3, 3,
            'message-assistant'
        )
        """)
    conn.execute(
        """
        INSERT INTO chat_attachments(
            attachment_id, session_id, turn_id, message_id, user_id, kind,
            original_name, mime_type, size_bytes, storage_rel_path, sha256,
            created_at_ms
        ) VALUES (
            'attachment-1', 'session-1', 'turn-1', 'message-assistant', 'u1',
            'file', 'attachment-private.txt', 'text/plain', 17, ?, 'hash', 2
        )
        """,
        (relative_attachment_path,),
    )
    conn.executemany(
        """
        INSERT INTO chat_message_asset_refs(
            message_id, asset_key, storage_rel_path, asset_kind, created_at_ms
        ) VALUES ('message-assistant', ?, ?, ?, 2)
        """,
        [
            (
                asset_path.resolve()
                .relative_to(runtime_paths.chat_resources_dir.resolve())
                .as_posix(),
                asset_path.resolve()
                .relative_to(runtime_paths.base_dir.resolve())
                .as_posix(),
                asset_kind,
            )
            for asset_path, asset_kind in (
                (attachment_path, "attachment"),
                (derived_path, "derived_text"),
            )
        ],
    )
    conn.execute("""
        INSERT INTO chat_context_summaries(
            summary_id, session_id, status, summary_kind, session_origin,
            summary_text, created_at_ms, updated_at_ms
        ) VALUES (
            'summary-1', 'session-1', 'active', 'token_budget', '',
            'assistant content', 1, 1
        )
        """)
    conn.execute("""
        INSERT INTO chat_user_turn_delivery(
            turn_id, projection_completed, delivery_attempt_no,
            delivery_state, current_command_id,
            runtime_envelope_json, request_fingerprint, created_at_ms,
            updated_at_ms
        ) VALUES (
            'turn-1', 1, 0, 'terminal', NULL,
            '{"message":"user content"}', 'fingerprint', 1, 1
        )
        """)
    conn.execute("""
        INSERT INTO chat_run_consumed_events(
            session_id, run_id, revision, message_id, recorded_at_ms
        ) VALUES ('session-1', 'run-1', 0, 'message-assistant', 1)
        """)
    conn.execute("""
        UPDATE chat_sessions
        SET summary = 'assistant content'
        WHERE session_id = 'session-1'
        """)
    conn.commit()
    conn.close()

    runtime_trace_db = runtime_paths.runtime_trace_db_path
    runtime_trace_db.parent.mkdir(parents=True, exist_ok=True)
    trace_conn = sqlite3.connect(runtime_trace_db)
    trace_conn.executescript(RUNTIME_TRACE_SCHEMA_SQL)
    trace_conn.execute("""
        INSERT INTO trace_turns(
            trace_id, turn_id, session_id, user_id, status, mode,
            started_at_ms, user_message_preview, response_preview,
            created_at_ms, updated_at_ms
        ) VALUES (
            'trace-1', 'turn-1', 'session-1', 'u1', 'completed', 'chat', 1,
            'private content', 'assistant content', 1, 1
        )
        """)
    trace_conn.execute("""
        INSERT INTO trace_llm_calls(
            span_id, trace_id, turn_id, provider, model, request_preview,
            response_preview
        ) VALUES (
            'span-1', 'trace-1', 'turn-1', 'test', 'test',
            'private content', 'assistant content'
        )
        """)
    trace_conn.execute("""
        INSERT INTO runtime_notifications(
            channel, user_id, session_id, turn_id, payload_json, created_at_ms
        ) VALUES (
            'agent_response', 'u1', 'session-1', 'turn-1',
            '{"content":"assistant content"}', 1
        )
        """)
    trace_conn.commit()
    trace_conn.close()
    return attachment_path, derived_path, runtime_trace_db


async def _upsert_assertion(
    memory: UnifiedMemoryStore,
    *,
    trait_name: str,
    trait_value: str,
    event_id: str,
) -> str:
    assert memory.l2 is not None
    return await memory.l2.upsert_assertion_candidate(
        {
            "entity_id": "user:u1",
            "entity_type": "user",
            "trait_family": "preference_profile",
            "trait_name": trait_name,
            "trait_value": trait_value,
            "confidence_score": 0.9,
            "evidence_events": [event_id],
            "volatility_index": 0.1,
            "source_domain": "conversation",
            "inference_depth": "explicit",
            "validation_state": "stable",
            "first_inferred_at": 1_720_000_000.0,
            "last_validated_at": 1_720_000_000.0,
            "temporal_scope": "persistent",
        }
    )


@pytest.mark.asyncio
async def test_real_session_delete_forgets_chat_memory_and_blocks_replay(
    tmp_path: Path,
) -> None:
    memory = await _build_memory(tmp_path)
    chat_db = tmp_path / "chat.db"
    _seed_chat_session(chat_db)
    read_service = ChatReadService()
    read_service._chat_db_path = chat_db
    read_service._delete_runtime_trace_rows = lambda **_kwargs: None  # type: ignore[method-assign]
    read_service._list_chat_snapshot_asset_references = (  # type: ignore[method-assign]
        lambda **_kwargs: []
    )
    read_service._delete_chat_message_assets = lambda **_kwargs: None  # type: ignore[method-assign]

    try:
        assert memory.l0 is not None
        assert memory.l1 is not None
        assert memory.l2 is not None
        assert memory.l3 is not None
        assert memory.l4 is not None
        await memory.l1.store(
            _memory_event(
                "event-1",
                session_id="session-1",
                turn_id="turn-1",
                content="private content",
            )
        )
        assertion_id = await memory.l2.upsert_assertion_candidate(
            {
                "entity_id": "user:u1",
                "entity_type": "user",
                "trait_family": "preference_profile",
                "trait_name": "private_preference",
                "trait_value": "private value",
                "confidence_score": 0.9,
                "evidence_events": ["turn-1"],
                "volatility_index": 0.1,
                "source_domain": "conversation",
                "inference_depth": "explicit",
                "validation_state": "stable",
                "first_inferred_at": 1_720_000_000.0,
                "last_validated_at": 1_720_000_000.0,
                "temporal_scope": "persistent",
            }
        )
        summary = await memory.l3.upsert_candidate(
            candidate=L3Candidate(
                summary_type="thematic",
                summary_category="topic",
                content="private summary",
                source_event_ids=["event-1"],
                insight_key="private-session-summary",
            )
        )
        preference_id = await memory.l4.record_task_preference(
            user_id="u1",
            persona_id="seven",
            task_category="coding",
            preference="private preference",
            evidence_text="private content",
            confidence=0.9,
            turn_id="turn-1",
        )
        assert preference_id is not None
        await _apply_attention(
            memory,
            session_id="session-1",
            actions=[
                _attention_action(
                    summary="Keep the private conversation detail in view",
                    kind=AttentionKind.FOCUS,
                    source_turn_ids=("turn-1",),
                    source_event_ids=("event-1",),
                )
            ],
            last_processed_turn_id="turn-1",
        )

        service = ChatForgettingService(
            chat_read_service=_DirectReadAdapter(read_service),
            chat_surface_write_service=_UnusedSurfaceWriter(),
            memory=memory,
            runtime=_NoopRuntimeForgettingCoordinator(),
        )
        await service.delete_session(user_id="u1", session_id="session-1")

        deleted_event = await memory.l1.get_event("event-1")
        assert deleted_event is not None and deleted_event["deleted_at"] is not None
        assertion = await memory.l2.get_tom_assertion(assertion_id=assertion_id)
        assert assertion is not None and assertion["status"] == "archived"
        assert await memory.l3.get_summary_by_id(summary["summary_id"]) is None
        assert await memory.l4.get_task_preferences(user_id="u1", task_category="coding") == []
        assert (await memory.l0.get_workbench("session-1"))["attention_items"] == []

        chat_conn = sqlite3.connect(chat_db)
        assert chat_conn.execute(
            "SELECT COUNT(*) FROM chat_messages WHERE session_id = 'session-1'"
        ).fetchone() == (0,)
        assert chat_conn.execute(
            "SELECT COUNT(*) FROM chat_turns WHERE session_id = 'session-1'"
        ).fetchone() == (0,)
        assert chat_conn.execute(
            "SELECT deleted_at_ms IS NOT NULL FROM chat_sessions WHERE session_id = 'session-1'"
        ).fetchone() == (1,)
        assert chat_conn.execute("""
            SELECT title, summary, last_message_preview,
                   last_user_message_preview, message_count, workspace_path
            FROM chat_sessions WHERE session_id = 'session-1'
            """).fetchone() == ("", "", "", "", 0, None)
        chat_conn.close()

        l1_conn = sqlite3.connect(memory.l1.db_path)
        assert l1_conn.execute("""
            SELECT title, summary, last_message_preview,
                   last_user_message_preview, message_count,
                   workspace_path, deleted_at IS NOT NULL
            FROM chat_sessions WHERE session_id = 'session-1'
            """).fetchone() == ("", "", "", "", 0, None, 1)
        l1_conn.close()

        session_reference = chat_session_source_reference(
            user_id="u1",
            session_id="session-1",
        )
        async with aiosqlite.connect(memory.memory_db_path) as db:
            async with db.execute(
                """
                SELECT event_id FROM memory_source_event_tombstones
                WHERE event_id IN (?, ?, ?)
                ORDER BY event_id
                """,
                ("event-1", "turn-1", session_reference),
            ) as cursor:
                assert {str(row[0]) for row in await cursor.fetchall()} == {
                    "event-1",
                    "turn-1",
                    session_reference,
                }

        replay_same_turn = await memory.ingest_event(
            _memory_event(
                "event-replay-turn",
                session_id="another-session",
                turn_id="turn-1",
                content="must stay forgotten",
            )
        )
        replay_same_session = await memory.ingest_event(
            _memory_event(
                "event-replay-session",
                session_id="session-1",
                turn_id="new-turn",
                content="must stay forgotten",
            )
        )
        assert replay_same_turn["skip_reason"] == "source_event_forgotten"
        assert replay_same_session["skip_reason"] == "source_event_forgotten"
        assert await memory.l1.get_event("event-replay-turn") is None
        assert await memory.l1.get_event("event-replay-session") is None
    finally:
        read_service.close()
        await memory.shutdown()


@pytest.mark.asyncio
async def test_rhythm_source_resolution_survives_hidden_first_segment(
    tmp_path: Path,
) -> None:
    chat_db = tmp_path / "chat.db"
    _seed_chat_turn_with_rhythm_segments(chat_db)
    read_service = ChatReadService()
    read_service._chat_db_path = chat_db
    try:
        with sqlite3.connect(chat_db) as connection:
            connection.execute(
                """
                UPDATE chat_messages
                SET sequence_no = sequence_no + 2
                WHERE message_id LIKE 'rhythm-%'
                """
            )
            for index in range(2):
                connection.execute(
                    """
                    INSERT INTO chat_messages(
                        message_id, session_id, turn_id, user_id, role,
                        message_kind, content_text, payload_json, is_final,
                        is_visible, created_at_ms, sequence_no
                    ) VALUES (?, 'session-1', 'turn-1', 'u1', 'assistant',
                              'assistant_rhythm_segment', '', ?, 1, 0, ?, ?)
                    """,
                    (
                        f"old-rhythm-{index + 1}",
                        json.dumps(
                            {
                                "rhythm": {
                                    "segment_index": index,
                                    "segment_count": 2,
                                }
                            }
                        ),
                        index + 2,
                        index + 2,
                    ),
                )
            connection.commit()

        second = read_service.get_message_source_identity(
            "u1",
            "session-1",
            "rhythm-2",
        )
        assert second is not None
        assert second.source_message_id == "rhythm-1"

        with sqlite3.connect(chat_db) as connection:
            connection.execute(
                """
                UPDATE chat_messages
                SET content_text = '', payload_json = '{}', is_visible = 0
                WHERE message_id = 'rhythm-1'
                """
            )
            connection.commit()

        last = read_service.get_message_source_identity(
            "u1",
            "session-1",
            "rhythm-3",
        )
        assert last is not None
        assert last.message_id == "rhythm-3"
        assert last.source_message_id == "rhythm-1"
    finally:
        read_service.close()


def test_replacement_chain_source_snapshot_includes_task_identity(
    tmp_path: Path,
) -> None:
    chat_db = tmp_path / "chat.db"
    _seed_chat_session(chat_db)
    with sqlite3.connect(chat_db) as connection:
        connection.execute(
            """
            INSERT INTO chat_messages(
                message_id, session_id, turn_id, user_id, role, message_kind,
                content_text, payload_json, is_final, is_visible, created_at_ms,
                sequence_no
            ) VALUES (
                'pending-1', 'session-1', 'turn-1', 'u1', 'assistant',
                'background_task_pending', 'pending',
                '{"background_task_id":"task-1"}', 0, 1, 2, 2
            )
            """
        )
        connection.execute(
            """
            INSERT INTO chat_messages(
                message_id, session_id, turn_id, user_id, role, message_kind,
                content_text, payload_json, is_final, is_visible, created_at_ms,
                sequence_no, replaces_message_id
            ) VALUES (
                'completion-1', 'session-1', 'turn-1', 'u1', 'assistant',
                'assistant_final', 'complete',
                '{"background_task_id":"task-1"}', 1, 1, 3, 3, 'pending-1'
            )
            """
        )
        connection.execute(
            """
            UPDATE chat_messages
            SET replaced_by_message_id = 'completion-1'
            WHERE message_id = 'pending-1'
            """
        )
        connection.commit()

    read_service = ChatReadService()
    read_service._chat_db_path = chat_db
    try:
        from_pending = (
            read_service.list_message_replacement_source_identities(
                "u1",
                "session-1",
                "pending-1",
            )
        )
        from_completion = (
            read_service.list_message_replacement_source_identities(
                "u1",
                "session-1",
                "completion-1",
            )
        )

        for identities in (from_pending, from_completion):
            assert [
                identity.message_id
                for identity in identities
            ] == ["pending-1", "completion-1"]
            assert {
                identity.background_task_id
                for identity in identities
            } == {"task-1"}
    finally:
        read_service.close()


@pytest.mark.asyncio
async def test_rhythm_last_segment_delete_forgets_whole_canonical_evidence(
    tmp_path: Path,
) -> None:
    memory = await _build_memory(tmp_path)
    chat_db = tmp_path / "chat.db"
    _seed_chat_turn_with_rhythm_segments(chat_db)
    read_service = ChatReadService()
    read_service._chat_db_path = chat_db
    read_service._runtime_paths = RuntimePaths(base_dir=tmp_path / "runtime-home")
    read_service._delete_runtime_trace_turn_rows = lambda **_kwargs: None  # type: ignore[method-assign]
    read_service._delete_chat_message_assets = lambda **_kwargs: None  # type: ignore[method-assign]

    try:
        assert memory.l1 is not None and memory.l2 is not None
        await memory.l1.store(
            _memory_event(
                "event-rhythm",
                session_id="session-1",
                turn_id="turn-1",
                message_id="rhythm-1",
                content="part 1\n\npart 2\n\npart 3",
                author_type="assistant",
            )
        )
        assertion_id = await _upsert_assertion(
            memory,
            trait_name="rhythm_supported_trait",
            trait_value="forget",
            event_id="event-rhythm",
        )
        service = ChatForgettingService(
            chat_read_service=_DirectReadAdapter(read_service),
            chat_surface_write_service=_DirectSurfaceWriter(chat_db),
            memory=memory,
            runtime=_NoopRuntimeForgettingCoordinator(),
        )

        assert await service.delete_message(
            user_id="u1",
            session_id="session-1",
            message_id="rhythm-3",
        )

        event = await memory.l1.get_event("event-rhythm")
        assertion = await memory.l2.get_tom_assertion(assertion_id=assertion_id)
        assert event is not None and event["deleted_at"] is not None
        assert assertion is not None and assertion["status"] == "archived"
        with sqlite3.connect(chat_db) as connection:
            rows = connection.execute(
                """
                SELECT message_id, content_text, is_visible
                FROM chat_messages
                WHERE message_id LIKE 'rhythm-%'
                ORDER BY sequence_no
                """
            ).fetchall()
        assert rows == [
            ("rhythm-1", "part 1", 1),
            ("rhythm-2", "part 2", 1),
        ]
    finally:
        read_service.close()
        await memory.shutdown()


@pytest.mark.asyncio
async def test_message_delete_forgets_only_that_message_and_blocks_its_replay(
    tmp_path: Path,
) -> None:
    memory = await _build_memory(tmp_path)
    chat_db = tmp_path / "chat.db"
    _seed_chat_turn_with_two_messages(chat_db)
    runtime_paths = RuntimePaths(base_dir=tmp_path / "runtime-home")
    attachment_path, derived_path, runtime_trace_db = _seed_message_artifacts(
        chat_db=chat_db,
        runtime_paths=runtime_paths,
    )
    read_service = ChatReadService()
    read_service._chat_db_path = chat_db
    read_service._runtime_paths = runtime_paths
    read_service._runtime_trace_db_path = runtime_trace_db
    read_service._asset_gc = ChatAssetGC(runtime_paths=runtime_paths)

    try:
        assert memory.l1 is not None and memory.l2 is not None
        await memory.l1.store(
            _memory_event(
                "event-user",
                session_id="session-1",
                turn_id="turn-1",
                message_id="message-1",
                content="user content",
            )
        )
        await memory.l1.store(
            _memory_event(
                "event-assistant",
                session_id="session-1",
                turn_id="turn-1",
                message_id="message-assistant",
                content="assistant content",
                author_type="assistant",
            )
        )
        user_assertion_id = await _upsert_assertion(
            memory,
            trait_name="user_supported_trait",
            trait_value="keep",
            event_id="event-user",
        )
        assistant_assertion_id = await _upsert_assertion(
            memory,
            trait_name="assistant_supported_trait",
            trait_value="forget",
            event_id="event-assistant",
        )

        service = ChatForgettingService(
            chat_read_service=_DirectReadAdapter(read_service),
            chat_surface_write_service=_DirectSurfaceWriter(chat_db),
            memory=memory,
            runtime=_NoopRuntimeForgettingCoordinator(),
        )
        assert await service.delete_message(
            user_id="u1",
            session_id="session-1",
            message_id="message-assistant",
        )

        user_event = await memory.l1.get_event("event-user")
        assistant_event = await memory.l1.get_event("event-assistant")
        assert user_event is not None and user_event["deleted_at"] is None
        assert assistant_event is not None and assistant_event["deleted_at"] is not None
        user_assertion = await memory.l2.get_tom_assertion(assertion_id=user_assertion_id)
        assistant_assertion = await memory.l2.get_tom_assertion(assertion_id=assistant_assertion_id)
        assert user_assertion is not None and user_assertion["status"] != "archived"
        assert assistant_assertion is not None and assistant_assertion["status"] == "archived"

        conn = sqlite3.connect(chat_db)
        conn.row_factory = sqlite3.Row
        target_row = conn.execute("""
            SELECT content_text, payload_json, is_visible, persona_id,
                   reply_to_message_id, label_json
            FROM chat_messages
            WHERE message_id = 'message-assistant'
            """).fetchone()
        reply_row = conn.execute(
            "SELECT reply_to_message_id FROM chat_messages WHERE message_id = 'message-reply'"
        ).fetchone()
        session_row = conn.execute("""
            SELECT title, summary, last_message_preview,
                   last_user_message_preview, message_count
            FROM chat_sessions WHERE session_id = 'session-1'
            """).fetchone()
        artifact_counts = {
            "attachments": conn.execute(
                "SELECT COUNT(*) FROM chat_attachments WHERE message_id = 'message-assistant'"
            ).fetchone()[0],
            "summaries": conn.execute(
                "SELECT COUNT(*) FROM chat_context_summaries WHERE session_id = 'session-1'"
            ).fetchone()[0],
            "delivery": conn.execute(
                "SELECT COUNT(*) FROM chat_user_turn_delivery WHERE turn_id = 'turn-1'"
            ).fetchone()[0],
            "consumed": conn.execute("""
                SELECT COUNT(*) FROM chat_run_consumed_events
                WHERE session_id = 'session-1' AND message_id = 'message-assistant'
                """).fetchone()[0],
        }
        conn.close()
        assert target_row is None
        assert reply_row is not None and reply_row[0] is None
        assert session_row is not None
        assert tuple(session_row) == (
            "Private",
            "",
            "private content",
            "private content",
            1,
        )
        assert artifact_counts == {
            "attachments": 0,
            "summaries": 0,
            "delivery": 1,
            "consumed": 0,
        }
        assert not attachment_path.exists()
        assert not derived_path.exists()
        assert (
            read_service.get_attachment_payload(
                "u1",
                "session-1",
                "attachment-1",
            )
            is None
        )
        assert all(
            "assistant content" not in message.content
            for message in read_service.get_conversation_history(
                "u1",
                "session-1",
                limit=None,
            )
        )
        context = await ChatContextAssembler(
            l1_db_path=Path(memory.l1.db_path),
            chat_store=ChatStore(db_path=str(chat_db)),
            chat_read_service_factory=lambda: read_service,
        ).get_or_load_history_context("u1", "session-1")
        assert "assistant content" not in str(context.messages)
        assert "assistant content" not in str(context.session_summary)

        trace_conn = sqlite3.connect(runtime_trace_db)
        assert trace_conn.execute(
            "SELECT COUNT(*) FROM trace_turns WHERE turn_id = 'turn-1'"
        ).fetchone() == (1,)
        assert trace_conn.execute(
            "SELECT COUNT(*) FROM trace_llm_calls WHERE turn_id = 'turn-1'"
        ).fetchone() == (1,)
        assert trace_conn.execute(
            "SELECT COUNT(*) FROM runtime_notifications WHERE turn_id = 'turn-1'"
        ).fetchone() == (1,)
        trace_conn.close()

        l1_conn = sqlite3.connect(memory.l1.db_path)
        assert l1_conn.execute("""
            SELECT last_message_preview, last_user_message_preview, message_count
            FROM chat_sessions WHERE session_id = 'session-1'
            """).fetchone() == ("user content", "user content", 1)
        l1_conn.close()

        message_references = set(
            business_source_references(
                source="chat",
                event_type="AIResponse",
                source_item_id="message-assistant",
                idempotency_key="message-assistant",
            )
        )
        async with aiosqlite.connect(memory.memory_db_path) as db:
            async with db.execute(
                "SELECT event_id FROM memory_source_event_tombstones",
            ) as cursor:
                tombstones = {str(row[0]) for row in await cursor.fetchall()}
                assert tombstones.intersection(
                    {"event-user", "event-assistant", "turn-1", *message_references}
                ) == {
                    "event-assistant",
                    *message_references,
                }

        replay = await memory.ingest_event(
            _memory_event(
                "event-assistant-replay",
                session_id="session-1",
                turn_id="turn-1",
                message_id="message-assistant",
                content="must remain forgotten",
                author_type="assistant",
            )
        )
        replay_with_changed_event_type = await memory.ingest_event(
            _memory_event(
                "event-assistant-replay-as-user",
                session_id="session-1",
                turn_id="turn-1",
                message_id="message-assistant",
                content="must remain forgotten across event types",
            )
        )
        unrelated_same_turn = await memory.ingest_event(
            _memory_event(
                "event-same-turn-new-message",
                session_id="session-1",
                turn_id="turn-1",
                message_id="message-new",
                content="must remain allowed",
                created_at=time.time(),
            )
        )
        assert replay["skip_reason"] == "source_event_forgotten"
        assert replay_with_changed_event_type["skip_reason"] == "source_event_forgotten"
        assert unrelated_same_turn["l1_written"] is True
    finally:
        read_service.close()
        await memory.shutdown()


@pytest.mark.asyncio
async def test_message_delete_keeps_unrelated_l0_state_across_retry_and_restart(
    tmp_path: Path,
) -> None:
    memory = await _build_memory(tmp_path)
    assert memory.l0 is not None and memory.l1 is not None
    deleted_event = _memory_event(
        "event-delete-l0",
        session_id="session-l0",
        turn_id="turn-delete-l0",
        message_id="message-delete-l0",
        content="delete this message",
    )
    retained_event = _memory_event(
        "event-keep-l0",
        session_id="session-l0",
        turn_id="turn-keep-l0",
        message_id="message-keep-l0",
        content="keep this message",
    )
    await memory.l1.store(deleted_event)
    await memory.l1.store(retained_event)
    await memory.l0.start_session(session_id="session-l0", user_id="u1")
    await _apply_attention(
        memory,
        session_id="session-l0",
        actions=[
            _attention_action(
                summary="Keep helping with the current conversation",
                source_turn_ids=(retained_event.turn_id,),
            ),
            _attention_action(
                summary="Deleted person is relevant",
                kind=AttentionKind.ACTIVE_OBJECT,
                source_turn_ids=(deleted_event.turn_id,),
                source_event_ids=(deleted_event.event_id,),
                entity_id="person:delete",
            ),
            _attention_action(
                summary="Retained person is relevant",
                kind=AttentionKind.ACTIVE_OBJECT,
                source_turn_ids=(retained_event.turn_id,),
                source_event_ids=(retained_event.event_id,),
                entity_id="person:keep",
            ),
            _attention_action(
                summary="Use the deleted message approach",
                kind=AttentionKind.CONSTRAINT,
                source_turn_ids=(deleted_event.turn_id,),
                source_event_ids=(deleted_event.event_id,),
            ),
            _attention_action(
                summary="Use the retained message approach",
                kind=AttentionKind.CONSTRAINT,
                source_turn_ids=(retained_event.turn_id,),
                source_event_ids=(retained_event.event_id,),
            ),
        ],
        last_processed_turn_id=retained_event.turn_id,
    )
    await memory.l0.checkpoint_session("session-l0")

    try:
        first = await memory.forget_chat_message_source(
            user_id="u1",
            session_id="session-l0",
            message_id="message-delete-l0",
            turn_id="turn-delete-l0",
            source="chat",
            event_type="UserMessage",
        )
        second = await memory.forget_chat_message_source(
            user_id="u1",
            session_id="session-l0",
            message_id="message-delete-l0",
            turn_id="turn-delete-l0",
            source="chat",
            event_type="UserMessage",
        )
        assert second.operation_id == first.operation_id

        workbench = await memory.l0.get_workbench("session-l0")
        assert workbench["session"] is not None
        assert sorted(
            item["summary"] for item in workbench["attention_items"]
        ) == [
            "Keep helping with the current conversation",
            "Retained person is relevant",
            "Use the retained message approach",
        ]
        assert {
            item["entity_id"]
            for item in workbench["attention_items"]
            if item["entity_id"] is not None
        } == {"person:keep"}
    finally:
        await memory.shutdown()

    restored = await _build_memory(tmp_path, initialize_schema=False)
    try:
        assert restored.l0 is not None
        workbench = await restored.l0.get_workbench("session-l0")
        assert workbench["session"] is not None
        assert sorted(
            item["summary"] for item in workbench["attention_items"]
        ) == [
            "Keep helping with the current conversation",
            "Retained person is relevant",
            "Use the retained message approach",
        ]
        assert {
            item["entity_id"]
            for item in workbench["attention_items"]
            if item["entity_id"] is not None
        } == {"person:keep"}
    finally:
        await restored.shutdown()


@pytest.mark.asyncio
async def test_user_message_delete_removes_owned_l0_attention(
    tmp_path: Path,
) -> None:
    memory = await _build_memory(tmp_path)
    assert memory.l0 is not None and memory.l1 is not None
    deleted_event = _memory_event(
        "event-delete-execution",
        session_id="session-delete-execution",
        turn_id="turn-delete-execution",
        message_id="message-delete-execution",
        content="private execution root",
    )
    await memory.l1.store(deleted_event)
    await _apply_attention(
        memory,
        session_id="session-delete-execution",
        actions=[
            _attention_action(
                summary="Private execution root remains active",
                source_turn_ids=(deleted_event.turn_id,),
                source_event_ids=(deleted_event.event_id,),
            ),
            _attention_action(
                summary="Retain unrelated attention",
                source_turn_ids=("turn-retained",),
            ),
        ],
        last_processed_turn_id=deleted_event.turn_id,
    )
    await memory.l0.checkpoint_session("session-delete-execution")

    try:
        await memory.forget_chat_message_source(
            user_id="u1",
            session_id="session-delete-execution",
            message_id="message-delete-execution",
            turn_id="turn-delete-execution",
            source="chat",
            event_type="UserMessage",
        )
        workbench = await memory.l0.get_workbench("session-delete-execution")
        assert [
            item["summary"] for item in workbench["attention_items"]
        ] == ["Retain unrelated attention"]
    finally:
        await memory.shutdown()

    restored = await _build_memory(tmp_path, initialize_schema=False)
    try:
        assert restored.l0 is not None
        workbench = await restored.l0.get_workbench("session-delete-execution")
        assert [
            item["summary"] for item in workbench["attention_items"]
        ] == ["Retain unrelated attention"]
    finally:
        await restored.shutdown()


@pytest.mark.asyncio
async def test_old_user_message_delete_preserves_concurrent_new_l0_attention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory = await _build_memory(tmp_path)
    assert memory.l0 is not None and memory.l1 is not None
    deleted_event = _memory_event(
        "event-delete-old-execution",
        session_id="session-concurrent-execution",
        turn_id="turn-old-execution",
        message_id="message-old-execution",
        content="old private root",
    )
    await memory.l1.store(deleted_event)
    await _apply_attention(
        memory,
        session_id="session-concurrent-execution",
        actions=[
            _attention_action(
                summary="Old private root remains active",
                source_turn_ids=(deleted_event.turn_id,),
                source_event_ids=(deleted_event.event_id,),
            )
        ],
        last_processed_turn_id=deleted_event.turn_id,
    )
    await memory.l0.checkpoint_session("session-concurrent-execution")

    cleanup_started = asyncio.Event()
    release_cleanup = asyncio.Event()
    runner = memory._durable_forget_runner
    original_cleanup_target = runner._cleanup_target

    async def pause_before_target_cleanup(operation):  # type: ignore[no-untyped-def]
        cleanup_started.set()
        await release_cleanup.wait()
        return await original_cleanup_target(operation)

    monkeypatch.setattr(runner, "_cleanup_target", pause_before_target_cleanup)
    try:
        deletion = asyncio.create_task(
            memory.forget_chat_message_source(
                user_id="u1",
                session_id="session-concurrent-execution",
                message_id="message-old-execution",
                turn_id="turn-old-execution",
                source="chat",
                event_type="UserMessage",
            )
        )
        await cleanup_started.wait()
        await _apply_attention(
            memory,
            session_id="session-concurrent-execution",
            actions=[
                _attention_action(
                    summary="New retained root remains active",
                    source_turn_ids=("turn-new-execution",),
                )
            ],
            last_processed_turn_id="turn-new-execution",
        )
        await memory.l0.checkpoint_session("session-concurrent-execution")
        release_cleanup.set()
        await deletion

        workbench = await memory.l0.get_workbench("session-concurrent-execution")
        assert [
            item["summary"] for item in workbench["attention_items"]
        ] == ["New retained root remains active"]
    finally:
        release_cleanup.set()
        await memory.shutdown()


@pytest.mark.asyncio
async def test_superseded_root_delete_removes_only_its_l0_attention(
    tmp_path: Path,
) -> None:
    memory = await _build_memory(tmp_path)
    assert memory.l0 is not None and memory.l1 is not None
    deleted_event = _memory_event(
        "event-superseded-root",
        session_id="session-superseded-root",
        turn_id="turn-old-root",
        message_id="message-old-root",
        content="old private root",
    )
    await memory.l1.store(deleted_event)
    await _apply_attention(
        memory,
        session_id="session-superseded-root",
        actions=[
            _attention_action(
                summary="Old superseded root",
                kind=AttentionKind.OPEN_LOOP,
                source_turn_ids=(deleted_event.turn_id,),
                source_event_ids=(deleted_event.event_id,),
            ),
            _attention_action(
                summary="New retained root",
                kind=AttentionKind.OPEN_LOOP,
                source_turn_ids=("turn-new-root",),
            ),
        ],
        last_processed_turn_id="turn-new-root",
    )
    await memory.l0.checkpoint_session("session-superseded-root")

    try:
        await memory.forget_chat_message_source(
            user_id="u1",
            session_id="session-superseded-root",
            message_id="message-old-root",
            turn_id="turn-old-root",
            source="chat",
            event_type="UserMessage",
        )
        workbench = await memory.l0.get_workbench("session-superseded-root")
        assert [
            item["summary"] for item in workbench["attention_items"]
        ] == ["New retained root"]
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_assistant_message_delete_preserves_user_l0_workbench(
    tmp_path: Path,
) -> None:
    memory = await _build_memory(tmp_path)
    assert (
        memory.l0 is not None
        and memory.l1 is not None
        and memory.l2 is not None
        and memory.l3 is not None
        and memory.l4 is not None
    )
    assistant_event = _memory_event(
        "event-delete-assistant-execution",
        session_id="session-assistant-execution",
        turn_id="turn-shared-execution",
        message_id="message-assistant-execution",
        content="assistant response",
        author_type="assistant",
    )
    await memory.l1.store(assistant_event)
    await _apply_attention(
        memory,
        session_id="session-assistant-execution",
        actions=[
            _attention_action(
                summary="Retain the user turn context",
                kind=AttentionKind.SITUATION,
                source_turn_ids=("turn-shared-execution",),
            )
        ],
        last_processed_turn_id="turn-shared-execution",
    )
    assertion_id = await _upsert_assertion(
        memory,
        trait_name="user_turn_preference",
        trait_value="retain",
        event_id="turn-shared-execution",
    )
    summary = await memory.l3.upsert_candidate(
        candidate=L3Candidate(
            summary_type="thematic",
            summary_category="topic",
            content="retain user turn summary",
            source_event_ids=["turn-shared-execution"],
            insight_key="retain-user-turn-summary",
        )
    )
    preference_id = await memory.l4.record_task_preference(
        user_id="u1",
        persona_id="seven",
        task_category="coding",
        preference="retain user turn preference",
        evidence_text="retain user root",
        confidence=0.9,
        turn_id="turn-shared-execution",
    )
    assert preference_id is not None
    await memory.l0.checkpoint_session("session-assistant-execution")

    try:
        await memory.forget_chat_message_source(
            user_id="u1",
            session_id="session-assistant-execution",
            message_id="message-assistant-execution",
            turn_id="turn-shared-execution",
            source="chat",
            event_type="AIResponse",
        )
        workbench = await memory.l0.get_workbench("session-assistant-execution")
        assert [
            item["summary"] for item in workbench["attention_items"]
        ] == ["Retain the user turn context"]
        assertion = await memory.l2.get_tom_assertion(assertion_id=assertion_id)
        assert assertion is not None and assertion["status"] != "archived"
        assert await memory.l3.get_summary_by_id(summary["summary_id"]) is not None
        assert len(
            await memory.l4.get_task_preferences(
                user_id="u1",
                task_category="coding",
            )
        ) == 1
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_session_forgetting_pages_through_every_matching_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import magi.memory.forgetting.runner as forgetting_runner

    memory = await _build_memory(tmp_path)
    monkeypatch.setattr(forgetting_runner, "_SELECTION_BATCH_SIZE", 2)
    try:
        assert memory.l1 is not None
        for index in range(5):
            await memory.l1.store(
                _memory_event(
                    f"event-page-{index}",
                    session_id="session-page",
                    turn_id=f"turn-page-{index}",
                    message_id=f"message-page-{index}",
                    content=f"page content {index}",
                )
            )

        outcome = await memory.forget_chat_session_sources(
            user_id="u1",
            session_id="session-page",
            turn_ids=[f"turn-page-{index}" for index in range(5)],
        )
        assert outcome.event_count == 5
        for index in range(5):
            event = await memory.l1.get_event(f"event-page-{index}")
            assert event is not None and event["deleted_at"] is not None
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "selector_kind",
    ["chat_session", "chat_message", "chat_history"],
)
async def test_completed_chat_forget_recovers_its_surface_after_restart(
    tmp_path: Path,
    selector_kind: str,
) -> None:
    memory = await _build_memory(tmp_path)
    chat_db = tmp_path / "chat.db"
    _seed_chat_session(chat_db)
    assert memory.l1 is not None
    await memory.l1.store(
        _memory_event(
            "event-before-crash",
            session_id="session-1",
            turn_id="turn-1",
            message_id="message-1",
            content="private content",
        )
    )

    crashed_read_service = ChatReadService()
    crashed_read_service._chat_db_path = chat_db
    crashed_read_service._delete_runtime_trace_rows = lambda **_kwargs: None  # type: ignore[method-assign]
    crashed_read_service._delete_runtime_trace_turn_rows = lambda **_kwargs: None  # type: ignore[method-assign]
    crashed_read_service._list_chat_snapshot_asset_references = (  # type: ignore[method-assign]
        lambda **_kwargs: []
    )
    crashed_read_service._delete_chat_message_assets = lambda **_kwargs: None  # type: ignore[method-assign]
    service = ChatForgettingService(
        chat_read_service=_CrashAfterMemoryReadAdapter(
            crashed_read_service,
            operation=selector_kind,
        ),
        chat_surface_write_service=_DirectSurfaceWriter(chat_db),
        memory=memory,
        runtime=_NoopRuntimeForgettingCoordinator(),
    )

    with pytest.raises(RuntimeError, match="simulated surface crash"):
        if selector_kind == "chat_session":
            await service.delete_session(user_id="u1", session_id="session-1")
        elif selector_kind == "chat_message":
            await service.delete_message(
                user_id="u1",
                session_id="session-1",
                message_id="message-1",
            )
        else:
            await service.clear_history(user_id="u1", session_id="session-1")

    async with aiosqlite.connect(memory.memory_db_path) as db:
        async with db.execute(
            """
            SELECT status, surface_finalized_at
            FROM memory_forget_operations
            WHERE selector_kind = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (selector_kind,),
        ) as cursor:
            assert await cursor.fetchone() == ("completed", None)
    crashed_read_service.close()
    await memory.shutdown()

    if selector_kind == "chat_history":
        _seed_new_message_after_crash(chat_db)

    recovered_memory = await _build_memory(tmp_path, initialize_schema=False)
    recovered_read_service = ChatReadService()
    recovered_read_service._chat_db_path = chat_db
    recovered_read_service._delete_runtime_trace_rows = lambda **_kwargs: None  # type: ignore[method-assign]
    recovered_read_service._delete_runtime_trace_turn_rows = lambda **_kwargs: None  # type: ignore[method-assign]
    recovered_read_service._list_chat_snapshot_asset_references = (  # type: ignore[method-assign]
        lambda **_kwargs: []
    )
    recovered_read_service._delete_chat_message_assets = lambda **_kwargs: None  # type: ignore[method-assign]
    finalizer = ChatSurfaceFinalizer(
        chat_read_service=_DirectReadAdapter(recovered_read_service),
        memory=recovered_memory,
    )
    try:
        assert await finalizer.recover_pending() == {"found": 1, "completed": 1}
        assert await finalizer.recover_pending() == {"found": 0, "completed": 0}

        with sqlite3.connect(chat_db) as connection:
            if selector_kind == "chat_session":
                assert connection.execute("""
                    SELECT deleted_at_ms IS NOT NULL
                    FROM chat_sessions
                    WHERE session_id = 'session-1'
                    """).fetchone() == (1,)
                assert connection.execute(
                    "SELECT COUNT(*) FROM chat_messages WHERE session_id = 'session-1'"
                ).fetchone() == (0,)
            elif selector_kind == "chat_message":
                assert connection.execute("""
                    SELECT COUNT(*)
                    FROM chat_messages
                    WHERE message_id = 'message-1'
                    """).fetchone() == (0,)
            if selector_kind == "chat_history":
                assert connection.execute("""
                    SELECT COUNT(*)
                    FROM chat_messages
                    WHERE message_id = 'message-1'
                    """).fetchone() == (0,)
                assert connection.execute("""
                    SELECT COUNT(*)
                    FROM chat_turns
                    WHERE turn_id = 'turn-1'
                    """).fetchone() == (0,)
                assert connection.execute("""
                    SELECT content_text, is_visible
                    FROM chat_messages
                    WHERE message_id = 'message-after-crash'
                    """).fetchone() == ("new content must survive", 1)

        async with aiosqlite.connect(recovered_memory.memory_db_path) as db:
            async with db.execute(
                """
                SELECT surface_finalized_at IS NOT NULL
                FROM memory_forget_operations
                WHERE selector_kind = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (selector_kind,),
            ) as cursor:
                assert await cursor.fetchone() == (1,)
    finally:
        recovered_read_service.close()
        await recovered_memory.shutdown()


@pytest.mark.asyncio
async def test_message_delete_barrier_wins_against_concurrent_reprojection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory = await _build_memory(tmp_path)
    barrier_written = asyncio.Event()
    release_delete = asyncio.Event()
    assert memory.l1 is not None
    await memory.l1.store(
        _memory_event(
            "event-race-original",
            session_id="session-race",
            turn_id="turn-race",
            message_id="message-race",
            content="original private source",
        )
    )
    repository = memory._durable_forget_runner._repository
    original_persist_page = repository.persist_event_page
    paused = False

    async def persist_page_then_pause(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal paused
        result = await original_persist_page(*args, **kwargs)
        if not paused:
            paused = True
            barrier_written.set()
            await release_delete.wait()
        return result

    monkeypatch.setattr(repository, "persist_event_page", persist_page_then_pause)
    try:
        delete_task = asyncio.create_task(
            memory.forget_chat_message_source(
                user_id="u1",
                session_id="session-race",
                message_id="message-race",
                turn_id="turn-race",
                source="chat",
                event_type="UserMessage",
            )
        )
        await barrier_written.wait()
        replay_task = asyncio.create_task(
            memory.ingest_event(
                _memory_event(
                    "event-race",
                    session_id="session-race",
                    turn_id="turn-race",
                    message_id="message-race",
                    content="must not be reprojected",
                )
            )
        )
        await asyncio.sleep(0)
        assert replay_task.done() is False

        release_delete.set()
        assert (await delete_task).event_count == 1
        replay_result = await replay_task
        assert replay_result["skip_reason"] == "source_event_forgotten"
        assert memory.l1 is not None
        assert await memory.l1.get_event("event-race") is None
    finally:
        release_delete.set()
        await memory.shutdown()


@pytest.mark.asyncio
async def test_claimed_assistant_outbox_cannot_reproject_after_delete_barrier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory = await _build_memory(tmp_path)
    chat_store = ChatStore(db_path=str(tmp_path / "chat-outbox-race.db"))
    await chat_store.initialize()
    barrier_written = asyncio.Event()
    release_delete = asyncio.Event()
    projection_started = asyncio.Event()
    release_projection = asyncio.Event()
    assert memory.l1 is not None
    async with aiosqlite.connect(chat_store.db_path) as db:
        await db.execute(
            """
            INSERT INTO chat_assistant_memory_outbox (
                canonical_message_id, user_id, session_id, turn_id,
                content_text, created_at_ms, state, attempt_count,
                next_attempt_at_ms, lease_token, lease_expires_at_ms,
                last_error, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, 0, NULL, NULL, NULL, ?)
            """,
            (
                "message-outbox-race",
                "u1",
                "session-outbox-race",
                "turn-outbox-race",
                "must not return",
                1_720_000_000_000,
                1_720_000_000_000,
            ),
        )
        await db.commit()

    repository = memory._durable_forget_runner._repository
    original_persist_references = repository.persist_selector_references
    paused = False

    async def persist_references_then_pause(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal paused
        result = await original_persist_references(*args, **kwargs)
        if not paused:
            paused = True
            barrier_written.set()
            await release_delete.wait()
        return result

    monkeypatch.setattr(
        repository,
        "persist_selector_references",
        persist_references_then_pause,
    )

    class _MemoryProjector:
        async def project_assistant_message(self, **kwargs):  # type: ignore[no-untyped-def]
            projection_started.set()
            await release_projection.wait()
            result = await memory.ingest_event(
                _memory_event(
                    "event-outbox-race-late",
                    session_id=str(kwargs["session_id"]),
                    turn_id=str(kwargs["turn_id"]),
                    message_id=str(kwargs["message_id"]),
                    content=str(kwargs["content"]),
                    author_type="assistant",
                )
            )
            assert result["skip_reason"] == "source_event_forgotten"
            return True

    async def read_clear_generation() -> int:
        return 0

    service = ChatAssistantMemoryProjectionService(
        outbox=chat_store,
        projector=_MemoryProjector(),  # type: ignore[arg-type]
        unified_memory=memory,
        clear_lifecycle=ChatMemoryProjectionClearLifecycle(
            read_current_clear_generation=read_clear_generation,
        ),
        confirmation_timeout_seconds=0.02,
        confirmation_poll_seconds=0.002,
        retry_base_seconds=0.01,
    )
    try:
        delete_task = asyncio.create_task(
            memory.forget_chat_message_source(
                user_id="u1",
                session_id="session-outbox-race",
                message_id="message-outbox-race",
                turn_id="turn-outbox-race",
                source="chat",
                event_type="AIResponse",
            )
        )
        await barrier_written.wait()
        projection_task = asyncio.create_task(service.process_ready_once())
        await projection_started.wait()
        assert projection_task.done() is False

        assert await chat_store.cancel_assistant_memory_projection(
            canonical_message_id="message-outbox-race"
        )
        release_delete.set()
        assert (await delete_task).event_count == 0
        release_projection.set()
        projection_stats = await projection_task

        assert projection_stats["cancelled"] == 1
        assert await chat_store.count_assistant_memory_projections() == 0
        assert (
            await memory.l1.find_event_id_by_idempotency(
                source="chat",
                event_type="AIResponse",
                idempotency_key="message-outbox-race",
            )
            is None
        )
        assert await memory.l1.get_event("event-outbox-race-late") is None
    finally:
        release_delete.set()
        release_projection.set()
        await chat_store.shutdown()
        await memory.shutdown()


@pytest.mark.asyncio
async def test_unknown_or_wrong_owner_session_never_creates_a_delete_barrier(
    tmp_path: Path,
) -> None:
    memory = await _build_memory(tmp_path)
    chat_db = tmp_path / "chat.db"
    _seed_chat_session(chat_db)
    read_service = ChatReadService()
    read_service._chat_db_path = chat_db
    read_service._delete_runtime_trace_rows = lambda **_kwargs: None  # type: ignore[method-assign]
    service = ChatForgettingService(
        chat_read_service=_DirectReadAdapter(read_service),
        chat_surface_write_service=_UnusedSurfaceWriter(),
        memory=memory,
        runtime=_NoopRuntimeForgettingCoordinator(),
    )

    try:
        assert await service.delete_session(user_id="wrong-user", session_id="session-1") is False
        assert await service.delete_session(user_id="u1", session_id="reusable-session") is False

        wrong_owner_reference = chat_session_source_reference(
            user_id="wrong-user",
            session_id="session-1",
        )
        reusable_reference = chat_session_source_reference(
            user_id="u1",
            session_id="reusable-session",
        )
        async with aiosqlite.connect(memory.memory_db_path) as db:
            async with db.execute(
                """
                SELECT event_id
                FROM memory_source_event_tombstones
                WHERE event_id IN (?, ?)
                """,
                (wrong_owner_reference, reusable_reference),
            ) as cursor:
                assert await cursor.fetchall() == []

        reused_session_id = read_service.create_new_session(
            "u1",
            idempotency_key="reusable-session",
        )
        ingest = await memory.ingest_event(
            _memory_event(
                "event-reused-session",
                session_id=reused_session_id,
                turn_id="turn-reused-session",
                message_id="message-reused-session",
                content="this new session must remain usable",
            )
        )
        assert ingest["l1_written"] is True
    finally:
        read_service.close()
        await memory.shutdown()


@pytest.mark.asyncio
async def test_chat_session_forgetting_is_repeatable_after_partial_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory = await _build_memory(tmp_path)
    try:
        assert memory.l1 is not None and memory.l3 is not None
        await memory.l1.store(
            _memory_event(
                "event-retry",
                session_id="session-retry",
                turn_id="turn-retry",
                content="retry content",
            )
        )
        original_forget = memory.l3.forget_source_events
        attempts = 0

        async def fail_once(event_ids):  # type: ignore[no-untyped-def]
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("temporary L3 cleanup failure")
            return await original_forget(event_ids)

        monkeypatch.setattr(memory.l3, "forget_source_events", fail_once)

        with pytest.raises(RuntimeError, match="temporary L3 cleanup failure"):
            await memory.forget_chat_session_sources(
                user_id="u1",
                session_id="session-retry",
                turn_ids=["turn-retry"],
            )
        event = await memory.l1.get_event("event-retry")
        assert event is not None and event["deleted_at"] is not None
        async with aiosqlite.connect(memory.memory_db_path) as db:
            async with db.execute("""
                SELECT status, phase
                FROM memory_forget_operations
                WHERE selector_kind = 'chat_session'
                ORDER BY created_at DESC
                LIMIT 1
                """) as cursor:
                assert await cursor.fetchone() == ("failed", "source_cleanup")

        outcome = await memory.forget_chat_session_sources(
            user_id="u1",
            session_id="session-retry",
            turn_ids=["turn-retry"],
        )
        assert outcome.event_count == 1
        event = await memory.l1.get_event("event-retry")
        assert event is not None and event["deleted_at"] is not None
        async with aiosqlite.connect(memory.memory_db_path) as db:
            async with db.execute("""
                SELECT status, phase
                FROM memory_forget_operations
                WHERE selector_kind = 'chat_session'
                ORDER BY created_at DESC
                LIMIT 1
                """) as cursor:
                assert await cursor.fetchone() == ("completed", "completed")
    finally:
        await memory.shutdown()
