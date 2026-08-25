from __future__ import annotations

from types import SimpleNamespace

import pytest

from magi.chat.contracts import ChatSessionRecord
from magi.chat.model_context import ModelContextItem, ModelContextItemKind
from magi.chat.store import ChatStore
from magi.chat.task_agent.context_assembler import ChatContextAssembler
from magi.chat.task_agent.model_context_port import ChatModelContextPort


class _VisibleHistory:
    def __init__(self) -> None:
        self.messages = [
            SimpleNamespace(
                message_id="message-1",
                role="assistant",
                content="old persona voice",
                persona_id="persona-a",
                message_kind="assistant_final",
                to_prompt_message=lambda: {
                    "role": "assistant",
                    "content": "old persona voice",
                },
            ),
            SimpleNamespace(
                message_id="message-2",
                role="user",
                content="continue",
                persona_id=None,
                message_kind="user_text",
                to_prompt_message=lambda: {"role": "user", "content": "continue"},
            ),
        ]

    def get_conversation_history(self, **kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return list(self.messages)

    def get_session_attachment_references(self, **kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return []


async def _create_session(store: ChatStore) -> None:
    await store.upsert_session(
        ChatSessionRecord(
            session_id="session-1",
            user_id="user-1",
            title="Test",
            title_overridden=False,
            summary="",
            created_at_ms=1,
            updated_at_ms=1,
            last_message_at_ms=None,
            last_user_message_at_ms=None,
            last_message_preview="",
            last_user_message_preview="",
            message_count=0,
            archived_at_ms=None,
            deleted_at_ms=None,
        )
    )


@pytest.mark.asyncio
async def test_persona_switch_rewrites_the_canonical_model_surface_once(tmp_path) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    await _create_session(store)
    original = await store.append_model_context(
        session_id="session-1",
        items=(
            ModelContextItem.from_prompt_message(
                {"role": "assistant", "content": "old persona voice"},
                source="model",
            ),
        ),
        expected_revision=0,
    )
    visible_history = _VisibleHistory()
    assembler = ChatContextAssembler(
        runtime_trace_db_path=tmp_path / "trace.db",
        chat_store=store,
        chat_read_service_factory=lambda: visible_history,
        persona_boundary_summary_generator=lambda summary_input: "neutral continuity",
    )

    first = await assembler.get_or_load_history_context(
        "user-1",
        "session-1",
        active_persona_id="persona-b",
    )

    assert first.version == original.revision
    assert len(first.messages) == 1
    assert "[persona_boundary:persona-b]" in first.messages[0]["content"]
    assert "neutral continuity" in first.messages[0]["content"]
    assert "old persona voice" not in str(first.messages)

    port = ChatModelContextPort(
        store=store,
        session_id="session-1",
        revision=first.version,
    )
    await port.commit(
        messages=first.messages,
        turn_id="turn-2",
        run_id="run-2",
        step_index=0,
    )
    second = await assembler.get_or_load_history_context(
        "user-1",
        "session-1",
        active_persona_id="persona-b",
    )
    snapshot = await store.load_model_context(session_id="session-1")

    assert second.version == snapshot.revision
    assert second.messages == first.messages
    assert snapshot.items[0].kind == ModelContextItemKind.COMPACTION_SUMMARY
