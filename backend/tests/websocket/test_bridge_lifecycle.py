from __future__ import annotations

import asyncio

import pytest
from dependency_injector import providers

from magi.backend_app import create_backend_app
from magi.core.container import get_container


class _FakeMessageBus:
    def __init__(self) -> None:
        self.subscriptions: list[tuple[str, str]] = []
        self.unsubscribed: list[str] = []

    async def subscribe(self, event_type: str, handler, propagation_mode: str = "competing") -> str:
        subscription_id = f"sub_{len(self.subscriptions) + 1}"
        self.subscriptions.append((subscription_id, event_type))
        return subscription_id

    async def unsubscribe(self, subscription_id: str) -> bool:
        self.unsubscribed.append(subscription_id)
        return True


class _DummyTraceService:
    def get_trace_snapshot(self, user_id: str, session_id: str, turn_id: str) -> dict:
        return {"summary": {"trace_available": False}, "orchestration_id": None}


@pytest.mark.asyncio
async def test_websocket_bridge_subscribes_after_runtime_message_bus_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_bus = _FakeMessageBus()

    async def _noop_runtime_lifecycle() -> None:
        return None

    monkeypatch.setattr("magi.backend_app.initialize_agent_runtime", _noop_runtime_lifecycle)
    monkeypatch.setattr("magi.backend_app.shutdown_agent_runtime", _noop_runtime_lifecycle)
    monkeypatch.setattr("magi.api.services.get_chat_trace_read_service", lambda: _DummyTraceService())
    monkeypatch.setattr(
        "magi.websocket.bridge_lifecycle.DEFAULT_WEBSOCKET_BRIDGE_RETRY_INTERVAL_SECONDS",
        0.01,
    )

    try:
        app = create_backend_app()
        async with app.router.lifespan_context(app):
            container = get_container()
            assert app.state.ai_response_subscription_id is None
            container.message_bus.override(providers.Object(fake_bus))

            for _ in range(100):
                if app.state.ai_response_subscription_id:
                    break
                await asyncio.sleep(0.01)

            assert app.state.ai_response_subscription_id is not None
            subscribed_event_types = {event_type for _, event_type in fake_bus.subscriptions}
            assert "AIResponse" in subscribed_event_types
            assert "WORKER_AGENT_PROGRESS" in subscribed_event_types
            assert "WORKER_AGENT_COMPLETED" in subscribed_event_types
            assert "WORKER_AGENT_FAILED" in subscribed_event_types
            assert "CHAT_TOOL_LOOP_STEP" in subscribed_event_types
            assert "TOOL_INTERACTION" in subscribed_event_types

        assert set(fake_bus.unsubscribed) == {sub_id for sub_id, _ in fake_bus.subscriptions}
    finally:
        get_container().message_bus.reset_override()
