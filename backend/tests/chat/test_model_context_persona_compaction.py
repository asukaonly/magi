from __future__ import annotations

import pytest

from magi.chat.contracts import ChatSessionRecord
from magi.chat.model_context import ModelContextItem, ModelContextItemKind
from magi.chat.store import ChatStore
from magi.chat.task_agent.context_assembler import ChatContextAssembler
from magi.chat.task_agent.model_context_port import ChatModelContextPort


class _VisibleHistory:
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
async def test_persona_switch_compacts_a_run_branch_without_rebuilding_from_chat(tmp_path) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    await _create_session(store)
    original = await store.append_model_context(
        session_id="session-1",
        items=(
            ModelContextItem.from_prompt_message(
                {"role": "assistant", "content": "old persona voice"},
                source="model",
                metadata={"persona_id": "persona-a"},
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
        run_id="run-2",
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
        persona_id="persona-b",
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
        run_id="run-2",
    )
    accepted = await store.load_model_context(session_id="session-1")
    working = await store.load_model_context(session_id="session-1", run_id="run-2")

    assert second.version == working.revision
    assert second.messages == first.messages
    assert accepted.revision == original.revision
    assert accepted.to_prompt_messages() == [
        {"role": "assistant", "content": "old persona voice"}
    ]
    assert working.items[0].kind == ModelContextItemKind.COMPACTION_SUMMARY


@pytest.mark.asyncio
async def test_persona_switch_back_preserves_canonical_tool_tail(tmp_path) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    await _create_session(store)
    await store.append_model_context(
        session_id="session-1",
        items=(
            ModelContextItem.from_prompt_message(
                {"role": "assistant", "content": "persona a old"},
                source="model",
                metadata={"persona_id": "persona-a"},
            ),
            ModelContextItem.from_prompt_message(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call-b",
                            "type": "function",
                            "function": {"name": "read", "arguments": "{}"},
                        }
                    ],
                },
                source="model",
                metadata={"persona_id": "persona-b"},
            ),
            ModelContextItem.from_prompt_message(
                {"role": "tool", "content": "foreign evidence", "tool_call_id": "call-b"},
                source="tool",
                metadata={"persona_id": "persona-b"},
            ),
            ModelContextItem.from_prompt_message(
                {"role": "user", "content": "continue as a"},
                source="user",
                metadata={"persona_id": "persona-a"},
            ),
            ModelContextItem.from_prompt_message(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call-a",
                            "type": "function",
                            "function": {"name": "search", "arguments": "{}"},
                        }
                    ],
                },
                source="model",
                metadata={"persona_id": "persona-a"},
            ),
            ModelContextItem.from_prompt_message(
                {"role": "tool", "content": "current evidence", "tool_call_id": "call-a"},
                source="tool",
                metadata={"persona_id": "persona-a"},
            ),
        ),
        expected_revision=0,
    )
    assembler = ChatContextAssembler(
        runtime_trace_db_path=tmp_path / "trace.db",
        chat_store=store,
        chat_read_service_factory=_VisibleHistory,
        persona_boundary_summary_generator=lambda summary_input: "neutral continuity",
    )

    history = await assembler.get_or_load_history_context(
        "user-1",
        "session-1",
        active_persona_id="persona-a",
        run_id="run-a",
    )

    assert "persona a old" not in str(history.messages)
    assert "foreign evidence" not in str(history.messages)
    assert history.messages[1:] == [
        {"role": "user", "content": "continue as a"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-a",
                    "type": "function",
                    "function": {"name": "search", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "content": "current evidence", "tool_call_id": "call-a"},
    ]
