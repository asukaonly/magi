from __future__ import annotations

from pathlib import Path

import pytest

from magi.agent.task_agents.chat.transcript_summarizer import (
    ChatTranscriptSummarizer,
    TranscriptSummaryInput,
)
from magi.chat import ChatMessageRecord, ChatStore


async def _append_assistant_message(
    store: ChatStore,
    *,
    session_id: str,
    user_id: str,
    turn_id: str,
    message_id: str,
    content: str,
    created_at_ms: int,
    sequence_no: int,
) -> None:
    await store.append_message(
        ChatMessageRecord(
            message_id=message_id,
            session_id=session_id,
            turn_id=turn_id,
            user_id=user_id,
            role="assistant",
            message_kind="assistant_final",
            content_text=content,
            payload_json="{}",
            is_final=True,
            is_visible=True,
            created_at_ms=created_at_ms,
            sequence_no=sequence_no,
            replaces_message_id=None,
            replaced_by_message_id=None,
        )
    )


@pytest.mark.asyncio
async def test_transcript_summarizer_rolls_previous_summary_into_next_summary(tmp_path: Path) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    await store.initialize()
    calls: list[TranscriptSummaryInput] = []

    async def summary_generator(summary_input: TranscriptSummaryInput) -> str:
        calls.append(summary_input)
        return f"summary {len(calls)}"

    try:
        for index in range(1, 5):
            turn_id = f"turn-{index}"
            await store.create_user_turn(
                session_id="session-1",
                user_id="user-1",
                turn_id=turn_id,
                message_text=f"user message {index} " + "x" * 80,
                created_at_ms=index * 100,
            )
            await _append_assistant_message(
                store,
                session_id="session-1",
                user_id="user-1",
                turn_id=turn_id,
                message_id=f"assistant-{index}",
                content=f"assistant answer {index} " + "y" * 80,
                created_at_ms=index * 100 + 50,
                sequence_no=index * 2,
            )

        summarizer = ChatTranscriptSummarizer(
            chat_store=store,
            summary_generator=summary_generator,
            token_threshold=1,
            tail_token_budget=70,
            min_messages=4,
        )

        first_result = await summarizer.maybe_summarize_session(
            user_id="user-1",
            session_id="session-1",
        )
        first_active = await store.get_active_context_summary(session_id="session-1")

        assert first_result.created is True
        assert first_active is not None
        assert first_active.summary_text == "summary 1"
        assert first_active.parent_summary_id is None
        assert first_active.first_kept_message_id is not None
        assert calls[0].previous_summary is None

        for index in range(5, 7):
            turn_id = f"turn-{index}"
            await store.create_user_turn(
                session_id="session-1",
                user_id="user-1",
                turn_id=turn_id,
                message_text=f"new user message {index} " + "z" * 80,
                created_at_ms=index * 100,
            )
            await _append_assistant_message(
                store,
                session_id="session-1",
                user_id="user-1",
                turn_id=turn_id,
                message_id=f"assistant-{index}",
                content=f"new assistant answer {index} " + "w" * 80,
                created_at_ms=index * 100 + 50,
                sequence_no=index * 2,
            )

        second_result = await summarizer.maybe_summarize_session(
            user_id="user-1",
            session_id="session-1",
        )
        second_active = await store.get_active_context_summary(session_id="session-1")

        assert second_result.created is True
        assert second_active is not None
        assert second_active.summary_text == "summary 2"
        assert second_active.parent_summary_id == first_active.summary_id
        assert calls[1].previous_summary == "summary 1"
        assert await store.get_history_version("session-1") == 8
    finally:
        await store.shutdown()
