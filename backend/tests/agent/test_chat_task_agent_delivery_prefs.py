"""ChatTaskAgent wires user_prefs_provider so fanout reads delivery_channels
from the config store.

Phase G+1 (Task 9 follow-up): The coordinator needs an async ``(user_id) -> dict``
provider so ``resolve_delivery_targets`` can pull the user's configured channels
(e.g. ``["chat_sse", "telegram"]``) out of the runtime config. Without this,
fanout silently defaults to chat_sse-only even when the user has multi-channel
prefs.

Today ``get_user_preference`` is process-wide (single-user model); the provider
ignores ``user_id`` for now. When a real per-user preference store lands,
that's the seam to swap.
"""
from __future__ import annotations

import pytest

from magi.chat.task_agent.chat_task_agent import ChatTaskAgent


class _FakeLLMAdapter:
    model_name = "fake-model"
    supports_embeddings = False


@pytest.mark.asyncio
async def test_user_prefs_provider_reads_delivery_channels_from_config(monkeypatch):
    """Provider returns the {"delivery_channels": [...]} shape expected by
    ``resolve_delivery_targets`` when the config has a non-empty list."""
    captured_keys: list[str] = []

    def fake_get_user_preference(key, default=None):
        captured_keys.append(key)
        if key == "delivery_channels":
            return ["chat_sse", "telegram"]
        return default

    import magi.chat.task_agent.chat_task_agent as cta_mod

    monkeypatch.setattr(cta_mod, "get_user_preference", fake_get_user_preference)

    agent = ChatTaskAgent(
        agent_id="u-chat",
        llm_adapter=_FakeLLMAdapter(),
        channel_registry_resolver=lambda: None,
    )
    provider = agent._coordinator._user_prefs_provider
    assert provider is not None

    prefs = await provider("u-test")
    assert prefs == {"delivery_channels": ["chat_sse", "telegram"]}
    assert "delivery_channels" in captured_keys


@pytest.mark.asyncio
async def test_user_prefs_provider_returns_empty_dict_when_no_preference(monkeypatch):
    """When delivery_channels is unset / falsy, return empty dict so the
    downstream resolver safely defaults to chat_sse-only delivery."""
    import magi.chat.task_agent.chat_task_agent as cta_mod

    monkeypatch.setattr(
        cta_mod, "get_user_preference", lambda k, default=None: default
    )

    agent = ChatTaskAgent(
        agent_id="u-chat",
        llm_adapter=_FakeLLMAdapter(),
        channel_registry_resolver=lambda: None,
    )
    prefs = await agent._coordinator._user_prefs_provider("u-test")
    assert prefs == {}


@pytest.mark.asyncio
async def test_user_prefs_provider_ignores_non_list_value(monkeypatch):
    """Defensive: when the stored preference is not a list (e.g. legacy string),
    treat it as unset and return empty so resolution falls back to default."""
    import magi.chat.task_agent.chat_task_agent as cta_mod

    monkeypatch.setattr(
        cta_mod,
        "get_user_preference",
        lambda k, default=None: "telegram" if k == "delivery_channels" else default,
    )

    agent = ChatTaskAgent(
        agent_id="u-chat",
        llm_adapter=_FakeLLMAdapter(),
        channel_registry_resolver=lambda: None,
    )
    prefs = await agent._coordinator._user_prefs_provider("u-test")
    assert prefs == {}


@pytest.mark.asyncio
async def test_user_prefs_provider_empty_list_returns_empty_dict(monkeypatch):
    """An empty list should be treated as 'no preference set' — return {}
    rather than {'delivery_channels': []} which would suppress all delivery."""
    import magi.chat.task_agent.chat_task_agent as cta_mod

    monkeypatch.setattr(
        cta_mod,
        "get_user_preference",
        lambda k, default=None: [] if k == "delivery_channels" else default,
    )

    agent = ChatTaskAgent(
        agent_id="u-chat",
        llm_adapter=_FakeLLMAdapter(),
        channel_registry_resolver=lambda: None,
    )
    prefs = await agent._coordinator._user_prefs_provider("u-test")
    assert prefs == {}
