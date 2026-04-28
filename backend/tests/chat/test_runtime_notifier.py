"""Tests for ChatRuntimeNotifier.emit_context_usage."""
from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from magi.agent.task_agents.chat.postprocess_components import ChatRuntimeNotifier
from magi.runtime_trace import RuntimeNotificationRecord


@dataclass
class _CapturedNotification:
    record: RuntimeNotificationRecord


class _FakeTraceStore:
    def __init__(self) -> None:
        self.notifications: list[RuntimeNotificationRecord] = []

    async def append_notification(self, record: RuntimeNotificationRecord) -> int:
        self.notifications.append(record)
        return len(self.notifications)


def _unused_read_service_factory() -> None:
    return None


class TestEmitContextUsage:
    @pytest.mark.asyncio
    async def test_emits_context_usage_notification(self) -> None:
        store = _FakeTraceStore()
        notifier = ChatRuntimeNotifier(
            runtime_trace_store=store,
            chat_read_service_factory=_unused_read_service_factory,
        )

        await notifier.emit_context_usage(
            user_id="u1",
            session_id="s1",
            turn_id="t1",
            context_usage={"used_tokens": 50_000, "window_size": 128_000, "threshold": 96_000},
        )

        assert len(store.notifications) == 1
        n = store.notifications[0]
        assert n.channel == "context_usage"
        assert n.user_id == "u1"
        assert n.session_id == "s1"
        assert n.turn_id == "t1"
        payload = json.loads(n.payload_json)
        assert payload["used_tokens"] == 50_000
        assert payload["window_size"] == 128_000
        assert payload["threshold"] == 96_000

    @pytest.mark.asyncio
    async def test_skips_when_no_trace_store(self) -> None:
        notifier = ChatRuntimeNotifier(
            runtime_trace_store=None,
            chat_read_service_factory=_unused_read_service_factory,
        )
        # Should not raise
        await notifier.emit_context_usage(
            user_id="u1",
            session_id="s1",
            turn_id="t1",
            context_usage={"used_tokens": 100, "window_size": 1000, "threshold": 800},
        )

    @pytest.mark.asyncio
    async def test_skips_when_empty_turn_id(self) -> None:
        store = _FakeTraceStore()
        notifier = ChatRuntimeNotifier(
            runtime_trace_store=store,
            chat_read_service_factory=_unused_read_service_factory,
        )

        await notifier.emit_context_usage(
            user_id="u1",
            session_id="s1",
            turn_id="",
            context_usage={"used_tokens": 100, "window_size": 1000, "threshold": 800},
        )
        assert len(store.notifications) == 0
