"""Tests for ChatPostProcessService.deliver_background_task_completion (Phase 4a)."""

from __future__ import annotations

import json

import pytest

from magi.agent.background.contracts import (
    BackgroundTask,
    BackgroundTaskSpec,
    BackgroundTaskStatus,
    BackgroundTaskTriggerSource,
)
from magi.agent.task_agents.chat.postprocess_service import ChatPostProcessService
from magi.chat import ChatStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def chat_store(tmp_path):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    await store.initialize()
    try:
        yield store
    finally:
        await store.shutdown()


def _make_service(chat_store: ChatStore | None) -> ChatPostProcessService:
    class _NoopHistory:
        async def append(self, *args, **kwargs) -> None:
            return None

    return ChatPostProcessService(
        agent_id="chat:u1",
        history_service=_NoopHistory(),  # type: ignore[arg-type]
        get_event_emitter=lambda: None,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        chat_store=chat_store,
        max_fact_memory=10,
    )


def _make_task(
    *,
    status: BackgroundTaskStatus = BackgroundTaskStatus.SUCCEEDED,
    title: str = "Audit release notes",
    summary: str | None = "Wrapped up. 12 PRs scanned, 3 follow-ups noted.",
    error: str | None = None,
    cancel_reason: str | None = None,
    session_id: str = "s1",
    user_id: str = "u1",
    finished_at: float | None = 1_710_000_000.5,
    trigger_source: BackgroundTaskTriggerSource = BackgroundTaskTriggerSource.RULE,
) -> BackgroundTask:
    spec = BackgroundTaskSpec(
        user_id=user_id,
        session_id=session_id,
        origin_turn_id="turn-1",
        title=title,
        goal="goal text",
        selected_tools=["deep_research"],
        trigger_source=trigger_source,
    )
    task = BackgroundTask.new(spec)
    task.status = status
    task.attempt_index = 1
    task.summary = summary
    task.error = error
    task.cancel_reason = cancel_reason
    task.finished_at = finished_at
    task.updated_at = finished_at or task.updated_at
    return task


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_succeeded_task_with_summary_persists_assistant_message(
    chat_store: ChatStore,
) -> None:
    service = _make_service(chat_store)
    task = _make_task()

    record = await service.deliver_background_task_completion(task)

    assert record is not None
    assert record.role == "assistant"
    assert record.message_kind == "assistant_final"
    assert record.session_id == "s1"
    assert record.user_id == "u1"
    assert record.turn_id is None
    assert record.is_final is True
    assert record.is_visible is True
    assert "[Background task]" not in (record.content_text or "")
    assert "12 PRs scanned" in (record.content_text or "")

    payload = json.loads(record.payload_json)
    assert payload["background_task_id"] == task.task_id
    assert payload["background_task_status"] == "succeeded"
    assert payload["background_task_title"] == "Audit release notes"
    assert payload["background_task_attempt"] == 1
    assert payload["trigger_source"] == "rule"


@pytest.mark.asyncio
async def test_scheduled_task_persists_plain_assistant_message(chat_store: ChatStore) -> None:
    service = _make_service(chat_store)
    task = _make_task(
        title="Drink water reminder",
        summary="该喝水啦。",
        trigger_source=BackgroundTaskTriggerSource.SCHEDULE,
    )

    record = await service.deliver_background_task_completion(task)

    assert record is not None
    assert record.role == "assistant"
    assert record.message_kind == "assistant_final"
    assert record.session_id == "s1"
    assert record.user_id == "u1"
    assert record.turn_id is None
    assert record.content_text == "该喝水啦。"
    assert "[Background task]" not in (record.content_text or "")
    payload = json.loads(record.payload_json)
    assert payload["background_task_id"] == task.task_id
    assert payload["background_task_status"] == "succeeded"
    assert payload["background_task_title"] == "Drink water reminder"
    assert payload["trigger_source"] == "schedule"


@pytest.mark.asyncio
async def test_succeeded_task_uses_finished_at_timestamp(chat_store: ChatStore) -> None:
    service = _make_service(chat_store)
    task = _make_task(finished_at=1_710_000_000.5)

    record = await service.deliver_background_task_completion(task)

    assert record is not None
    # finished_at (seconds) -> milliseconds.
    assert record.created_at_ms == 1_710_000_000_500


@pytest.mark.asyncio
async def test_succeeded_task_falls_back_to_no_summary_placeholder(
    chat_store: ChatStore,
) -> None:
    service = _make_service(chat_store)
    task = _make_task(summary=None)

    record = await service.deliver_background_task_completion(task)

    assert record is not None
    assert record.role == "system"
    assert record.message_kind == "background_task_completion"
    assert "(no summary)" in (record.content_text or "")


@pytest.mark.asyncio
async def test_failed_task_message_carries_error_reason(chat_store: ChatStore) -> None:
    service = _make_service(chat_store)
    task = _make_task(
        status=BackgroundTaskStatus.FAILED,
        summary=None,
        error="tool exploded",
    )

    record = await service.deliver_background_task_completion(task)

    assert record is not None
    assert record.role == "system"
    assert record.message_kind == "background_task_completion"
    assert "Background task failed: tool exploded" in (record.content_text or "")
    payload = json.loads(record.payload_json)
    assert payload["background_task_status"] == "failed"


@pytest.mark.asyncio
async def test_cancelled_task_message_carries_cancel_reason(chat_store: ChatStore) -> None:
    service = _make_service(chat_store)
    task = _make_task(
        status=BackgroundTaskStatus.CANCELLED,
        summary=None,
        cancel_reason="user_interrupt",
    )

    record = await service.deliver_background_task_completion(task)

    assert record is not None
    assert record.role == "system"
    assert record.message_kind == "background_task_completion"
    assert "Background task cancelled: user_interrupt" in (record.content_text or "")


@pytest.mark.asyncio
async def test_summary_is_truncated_when_over_max_chars(chat_store: ChatStore) -> None:
    service = _make_service(chat_store)
    task = _make_task(summary="A" * 5000)

    record = await service.deliver_background_task_completion(
        task, summary_max_chars=200
    )

    assert record is not None
    body = record.content_text or ""
    # 200 chars + ellipsis suffix.
    assert body.endswith("...")
    assert len(body) <= 203


@pytest.mark.asyncio
async def test_bumps_history_version_so_ui_refreshes(chat_store: ChatStore) -> None:
    service = _make_service(chat_store)
    task = _make_task()
    await chat_store.create_user_turn(
        session_id="s1",
        user_id="u1",
        turn_id="seed-turn",
        message_text="seed",
        created_at_ms=1_710_000_000_000,
    )

    before = await chat_store.get_history_version("s1")
    await service.deliver_background_task_completion(task)
    after = await chat_store.get_history_version("s1")

    assert after == before + 1


@pytest.mark.asyncio
async def test_returns_none_when_chat_store_unwired() -> None:
    service = _make_service(None)
    task = _make_task()

    record = await service.deliver_background_task_completion(task)

    assert record is None


@pytest.mark.asyncio
async def test_returns_none_for_blank_session_or_user(chat_store: ChatStore) -> None:
    service = _make_service(chat_store)
    blank_session = _make_task(session_id="")
    blank_user = _make_task(user_id="   ")

    assert await service.deliver_background_task_completion(blank_session) is None
    assert await service.deliver_background_task_completion(blank_user) is None


@pytest.mark.asyncio
async def test_falls_back_to_default_title_when_spec_title_blank(
    chat_store: ChatStore,
) -> None:
    service = _make_service(chat_store)
    task = _make_task(title="   ", summary=None)

    record = await service.deliver_background_task_completion(task)

    assert record is not None
    assert "[Background task] Background task" in (record.content_text or "")
