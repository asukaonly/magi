from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from magi.chat import ChatMessageRecord, ChatStore
from magi.chat.task_agent.recall_feedback_context import ChatRecallFeedbackContextMixin
from magi.events.recall_feedback import RecallFeedbackKind, RecallFeedbackRequest


class _Resolver(ChatRecallFeedbackContextMixin):
    def __init__(self, chat_store: ChatStore) -> None:
        self._chat_store = chat_store


async def _seed_memory_answer(store: ChatStore) -> None:
    await store.create_user_turn(
        session_id="session-1",
        user_id="user-1",
        turn_id="turn-1",
        message_text="What did I browse?",
        created_at_ms=100,
    )
    await store.append_message(
        ChatMessageRecord(
            message_id="assistant-1",
            session_id="session-1",
            turn_id="turn-1",
            user_id="user-1",
            role="assistant",
            message_kind="assistant_final",
            content_text="You browsed two pages.",
            payload_json=json.dumps(
                {
                    "recalled_memories": [
                        {
                            "kind": "event",
                            "source_layer": "L1",
                            "statement": "Visited example.com",
                            "topic": "example.com",
                            "feedback_ref": "event:event-1",
                        },
                        {
                            "kind": "event",
                            "source_layer": "L1",
                            "statement": "Visited docs.example.com",
                            "topic": "docs.example.com",
                            "feedback_ref": "event:event-2",
                        },
                    ],
                    "recalled_memory_summary": {
                        "coverage_kind": "exhaustive",
                        "can_claim_total": True,
                        "total_count": 2,
                    },
                }
            ),
            is_final=True,
            is_visible=True,
            created_at_ms=150,
            sequence_no=2,
            replaces_message_id=None,
            replaced_by_message_id=None,
        )
    )


@pytest.mark.asyncio
async def test_item_feedback_removes_only_the_targeted_snapshot_record(
    runtime_paths_with_schema,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await store.initialize()
    await _seed_memory_answer(store)

    context = await _Resolver(store)._resolve_recall_feedback_context(
        SimpleNamespace(
            user_id="user-1",
            session_id="session-1",
            recall_feedback=RecallFeedbackRequest(
                kind=RecallFeedbackKind.ITEM_IRRELEVANT,
                target_message_id="assistant-1",
                finding_ref="event:event-1",
            ),
        )
    )

    assert context is not None
    assert context.valid is True
    assert context.original_question == "What did I browse?"
    assert [item["feedback_ref"] for item in context.recalled_memories] == ["event:event-2"]
    assert context.recalled_memory_summary is None


@pytest.mark.asyncio
async def test_answer_feedback_keeps_the_exact_displayed_evidence_snapshot(
    runtime_paths_with_schema,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await store.initialize()
    await _seed_memory_answer(store)

    context = await _Resolver(store)._resolve_recall_feedback_context(
        SimpleNamespace(
            user_id="user-1",
            session_id="session-1",
            recall_feedback=RecallFeedbackRequest(
                kind=RecallFeedbackKind.ANSWER_EVIDENCE_MISMATCH,
                target_message_id="assistant-1",
            ),
        )
    )

    assert context is not None
    assert context.valid is True
    assert len(context.recalled_memories) == 2
    assert context.recalled_memory_summary == {
        "coverage_kind": "exhaustive",
        "can_claim_total": True,
        "total_count": 2,
    }


@pytest.mark.asyncio
async def test_feedback_on_a_correction_keeps_the_original_question(
    runtime_paths_with_schema,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await store.initialize()
    await _seed_memory_answer(store)
    await store.create_user_turn(
        session_id="session-1",
        user_id="user-1",
        turn_id="turn-2",
        message_text="That first record was irrelevant.",
        created_at_ms=200,
    )
    await store.append_message(
        ChatMessageRecord(
            message_id="assistant-2",
            session_id="session-1",
            turn_id="turn-2",
            user_id="user-1",
            role="assistant",
            message_kind="assistant_final",
            content_text="Then only the docs page is supported.",
            payload_json=json.dumps(
                {
                    "corrects_message_id": "assistant-1",
                    "recalled_memories": [
                        {
                            "kind": "event",
                            "source_layer": "L1",
                            "statement": "Visited docs.example.com",
                            "topic": "docs.example.com",
                            "feedback_ref": "event:event-2",
                        }
                    ],
                }
            ),
            is_final=True,
            is_visible=True,
            created_at_ms=250,
            sequence_no=2,
            replaces_message_id=None,
            replaced_by_message_id=None,
        )
    )

    context = await _Resolver(store)._resolve_recall_feedback_context(
        SimpleNamespace(
            user_id="user-1",
            session_id="session-1",
            recall_feedback=RecallFeedbackRequest(
                kind=RecallFeedbackKind.ANSWER_EVIDENCE_MISMATCH,
                target_message_id="assistant-2",
            ),
        )
    )

    assert context is not None
    assert context.valid is True
    assert context.original_question == "What did I browse?"
    assert [item["feedback_ref"] for item in context.recalled_memories] == ["event:event-2"]


@pytest.mark.asyncio
async def test_feedback_cannot_target_another_session(
    runtime_paths_with_schema,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await store.initialize()
    await _seed_memory_answer(store)

    context = await _Resolver(store)._resolve_recall_feedback_context(
        SimpleNamespace(
            user_id="user-1",
            session_id="session-2",
            recall_feedback=RecallFeedbackRequest(
                kind=RecallFeedbackKind.ANSWER_EVIDENCE_MISMATCH,
                target_message_id="assistant-1",
            ),
        )
    )

    assert context is not None
    assert context.valid is False
    assert context.error_code == "target_message_unavailable"
