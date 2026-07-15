from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from magi.chat.task_agent.transcript_summarizer import (
    ChatTranscriptSummarizer,
    TranscriptMessageForSummary,
    TranscriptSummaryInput,
)
from magi.chat import ChatMessageRecord, ChatStore
from magi.context.window_budget import build_context_window_budget
from magi.llm.model_context import ModelContextProfile, ResolvedModel


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
async def test_transcript_summarizer_rolls_previous_summary_into_next_summary(
    runtime_paths_with_schema,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
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

        with patch.object(store, "list_messages", wraps=store.list_messages) as list_messages:
            second_result = await summarizer.maybe_summarize_session(
                user_id="user-1",
                session_id="session-1",
            )
        list_messages.assert_awaited_once_with(
            session_id="session-1",
            start_message_id=first_active.first_kept_message_id,
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


def test_transcript_summarizer_recomputes_threshold_for_active_model() -> None:
    current = {
        "profile": ModelContextProfile(
            provider_id="provider-a",
            model_id="large-model",
            context_window=1_000_000,
            max_output_tokens=64_000,
        )
    }
    summarizer = ChatTranscriptSummarizer(
        chat_store=None,
        model_context_provider=lambda: current["profile"],
        min_messages=4,
    )
    messages = [
        TranscriptMessageForSummary(
            message_id=f"message-{index}",
            role="user" if index % 2 == 0 else "assistant",
            content="x" * 100_000,
            sequence_no=index,
            created_at_ms=index,
        )
        for index in range(4)
    ]

    large_plan = summarizer._build_summary_plan(
        active_summary=None,
        transcript_messages=messages,
    )
    assert large_plan.reason == "below_threshold"

    current["profile"] = ModelContextProfile(
        provider_id="provider-b",
        model_id="small-model",
        context_window=128_000,
        max_output_tokens=8_000,
    )
    small_plan = summarizer._build_summary_plan(
        active_summary=None,
        transcript_messages=messages,
    )
    assert not hasattr(small_plan, "reason")


def test_transcript_summarizer_estimates_chinese_history_conservatively() -> None:
    ascii_tokens = ChatTranscriptSummarizer._estimate_prompt_messages_tokens(
        [{"role": "user", "content": "a" * 400}]
    )
    chinese_tokens = ChatTranscriptSummarizer._estimate_prompt_messages_tokens(
        [{"role": "user", "content": "你" * 400}]
    )

    assert chinese_tokens > ascii_tokens * 3


def test_transcript_summarizer_ignores_message_count_gate_under_token_pressure() -> None:
    summarizer = ChatTranscriptSummarizer(
        chat_store=None,
        model_context_provider=lambda: ModelContextProfile(
            provider_id="provider-a",
            model_id="small-model",
            context_window=128_000,
            max_output_tokens=8_000,
        ),
    )
    messages = [
        TranscriptMessageForSummary(
            message_id=f"message-{index}",
            role="user" if index % 2 == 0 else "assistant",
            content="x" * 240_000,
            sequence_no=index,
            created_at_ms=index,
        )
        for index in range(4)
    ]

    plan = summarizer._build_summary_plan(
        active_summary=None,
        transcript_messages=messages,
    )

    assert not hasattr(plan, "reason")
    assert [message.message_id for message in plan.messages_to_summarize] == [
        "message-0",
        "message-1",
    ]


def test_transcript_summarizer_keeps_complete_user_turn_at_summary_frontier() -> None:
    summarizer = ChatTranscriptSummarizer(
        chat_store=None,
        summary_generator=lambda summary_input: "summary",
        token_threshold=1,
        tail_token_budget=100,
        min_messages=2,
    )
    messages = [
        TranscriptMessageForSummary("u1", "user", "first question", 1, 1),
        TranscriptMessageForSummary("a1", "assistant", "first answer", 2, 2),
        TranscriptMessageForSummary(
            "u2",
            "user",
            "second question " + "x" * 5_000,
            3,
            3,
        ),
        TranscriptMessageForSummary("a2", "assistant", "short second answer", 4, 4),
    ]

    plan = summarizer._build_summary_plan(
        active_summary=None,
        transcript_messages=messages,
    )

    assert [message.message_id for message in plan.messages_to_summarize] == ["u1", "a1"]
    assert messages[plan.tail_start_index].message_id == "u2"


def test_transcript_summarizer_frontier_never_starts_inside_rhythm_segments() -> None:
    summarizer = ChatTranscriptSummarizer(
        chat_store=None,
        summary_generator=lambda summary_input: "summary",
        token_threshold=1,
        tail_token_budget=50,
        min_messages=2,
    )
    messages = [
        TranscriptMessageForSummary("u1", "user", "old question", 1, 1, turn_id="t1"),
        TranscriptMessageForSummary("a1", "assistant", "old answer", 2, 2, turn_id="t1"),
        TranscriptMessageForSummary("u2", "user", "new question", 1, 3, turn_id="t2"),
        TranscriptMessageForSummary("seg1", "assistant", "part one", 2, 4, turn_id="t2"),
        TranscriptMessageForSummary("seg2", "assistant", "part two", 3, 5, turn_id="t2"),
    ]

    plan = summarizer._build_summary_plan(
        active_summary=None,
        transcript_messages=messages,
    )

    assert messages[plan.tail_start_index].message_id == "u2"


def test_transcript_summary_keeps_full_message_and_attachment_references() -> None:
    long_content = "start-" + "x" * 6_000 + "-end"
    record = ChatMessageRecord(
        message_id="message-1",
        session_id="session-1",
        turn_id="turn-1",
        user_id="user-1",
        role="user",
        message_kind="user_text",
        content_text=long_content,
        payload_json=json.dumps(
            {
                "attachments": [
                    {
                        "attachment_id": "attachment-1",
                        "original_name": "report.pdf",
                        "kind": "pdf",
                    }
                ]
            }
        ),
        is_final=True,
        is_visible=True,
        created_at_ms=1,
        sequence_no=1,
        replaces_message_id=None,
        replaced_by_message_id=None,
    )

    messages = ChatTranscriptSummarizer._prompt_messages_from_records([record])
    rendered = ChatTranscriptSummarizer._render_messages(messages)

    assert "-end" in rendered
    assert "[truncated]" not in rendered
    assert "attachment-1" in rendered
    assert "report.pdf" in rendered


@pytest.mark.parametrize(
    ("context_window", "max_output_tokens", "expected_summary_tokens"),
    [
        (16_000, 4_000, 1_024),
        (128_000, 8_000, 6_000),
        (200_000, 8_000, 9_600),
        (1_000_000, 64_000, 16_384),
    ],
)
def test_transcript_summary_output_budget_scales_with_core_model(
    context_window: int,
    max_output_tokens: int,
    expected_summary_tokens: int,
) -> None:
    summarizer = ChatTranscriptSummarizer(
        chat_store=None,
        model_context_provider=lambda: ModelContextProfile(
            provider_id="core-provider",
            model_id="core-model",
            context_window=context_window,
            max_output_tokens=max_output_tokens,
        ),
    )
    summary_model_budget = build_context_window_budget(
        ModelContextProfile(
            provider_id="summary-provider",
            model_id="summary-model",
            context_window=1_000_000,
            max_output_tokens=64_000,
        )
    )

    assert (
        summarizer._resolve_summary_output_tokens(summary_model_budget) == expected_summary_tokens
    )


@pytest.mark.asyncio
async def test_transcript_summary_request_uses_summary_model_capacity() -> None:
    fake_adapter = SimpleNamespace()
    fake_pool = SimpleNamespace(
        resolve=lambda scenario: ResolvedModel(
            adapter=fake_adapter,
            context=ModelContextProfile(
                provider_id="summary-provider",
                model_id="small-summary-model",
                context_window=4_000,
                max_output_tokens=1_000,
            ),
        )
    )
    bridge = AsyncMock()
    bridge.chat = AsyncMock(return_value=SimpleNamespace(content="cumulative summary"))
    summarizer = ChatTranscriptSummarizer(
        chat_store=None,
        scenario_llm_pool=fake_pool,
    )
    summary_input = TranscriptSummaryInput(
        session_id="session-1",
        previous_summary=None,
        session_origin="origin",
        messages=[
            TranscriptMessageForSummary(
                message_id=f"message-{index}",
                role="user" if index % 2 == 0 else "assistant",
                content="x" * 4_000,
                sequence_no=index,
                created_at_ms=index,
            )
            for index in range(6)
        ],
    )

    with patch(
        "magi.chat.task_agent.transcript_summarizer.LLMProviderBridge",
        return_value=bridge,
    ):
        summary = await summarizer._generate_summary(summary_input)

    assert summary == "cumulative summary"
    assert bridge.chat.await_count > 1
    assert {call.kwargs["max_tokens"] for call in bridge.chat.await_args_list} == {1_000}
    assert all(
        "Keep the summary within 1000 tokens." in call.kwargs["system_prompt"]
        for call in bridge.chat.await_args_list
    )
