from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from magi_plugin_sdk.providers import (
    ExternalAgentEvent,
    ExternalAgentRequest,
    ExternalAgentResult,
    ModelEvent,
    ModelRequest,
    ModelResult,
    ProviderToolCall,
    ProviderUsage,
)
from magi_plugin_sdk.runtime import PluginConnection

from magi.llm.factory import create_llm_adapter, create_scenario_llm_pool
from magi.config import AppConfig
from magi.config.models import LLMSelectionSettings, LLMScenario
from magi.llm.provider_bridge import LLMProviderBridge
from magi.plugins.providers import PluginProviderRegistry
from magi.tools.code_agent.adapters.base import CancelToken
from magi.tools.code_agent.contracts import DelegateConstraints, DelegateRequest
from magi.tools.code_agent.service import CodeAgentService


@pytest.fixture
def providers():
    connections = {
        "account": PluginConnection(
            connection_id="account", plugin_id="test", display_name="Test", enabled=True
        )
    }
    return PluginProviderRegistry(get_connection=connections.get), connections


class ModelProvider:
    def __init__(self):
        self.requests = []
        self.closed = 0
        self.result = ModelResult(
            content="Hello",
            tool_calls=[
                ProviderToolCall(id="call1", name="lookup", arguments={"query": "test"})
            ],
            usage=ProviderUsage(input_tokens=10, output_tokens=2, total_tokens=12),
        )

    async def invoke(self, request):
        assert isinstance(request, ModelRequest)
        self.requests.append(request)
        return self.result

    async def stream(self, request):
        assert isinstance(request, ModelRequest)
        self.requests.append(request)
        try:
            yield ModelEvent(kind="text", delta="Hello")
            yield ModelEvent(kind="tool_call", tool_call=self.result.tool_calls[0])
            yield ModelEvent(kind="completed", result=self.result)
        finally:
            self.closed += 1


@pytest.mark.asyncio
async def test_factory_and_actual_bridge_preserve_sdk_tool_calls_and_streams(providers):
    registry, _ = providers
    provider = ModelProvider()
    dispose = registry.register(
        plugin_id="test",
        connection_id="account",
        kind="model",
        provider_id="account:model",
        implementation=provider,
    )
    adapter = create_llm_adapter(
        provider_type="account:model",
        api_key="",
        model="test-model",
        provider_registry=registry,
    )
    bridge = LLMProviderBridge(adapter)
    response = await bridge.chat_with_tools(
        "System",
        [{"role": "user", "content": "Question"}],
        [{"name": "lookup", "input_schema": {"type": "object"}}],
    )
    assert response.tool_calls[0].arguments == {"query": "test"}
    assert response.usage.total_tokens == 12
    assert provider.requests[0].identity.connection_id == "account"
    assert provider.requests[0].identity.principal_id == "local_user"
    assert provider.requests[0].messages[0]["role"] == "system"
    streamed = await adapter.stream_tool_response(
        messages=[{"role": "user", "content": "Question"}]
    )
    assert (
        streamed.has_tool_calls
        and streamed.provider_response.tool_calls[0].name == "lookup"
    )
    events = [
        event
        async for event in bridge.chat_response_stream(
            "", [{"role": "user", "content": "Question"}]
        )
    ]
    assert [event.text for event in events if event.kind == "text_delta"] == ["Hello"]
    assert [event.kind for event in events].count("done") == 1
    assert provider.closed == 2
    dispose()
    with pytest.raises(RuntimeError, match="revoked"):
        await adapter.chat([{"role": "user", "content": "Again"}])


@pytest.mark.asyncio
async def test_model_stream_deadline_closes_worker_stream(providers):
    registry, _ = providers
    closed = asyncio.Event()

    class Slow(ModelProvider):
        async def stream(self, request):
            try:
                await asyncio.Event().wait()
                yield ModelEvent(kind="completed", result=self.result)
            finally:
                closed.set()

    registry.register(
        plugin_id="test",
        connection_id="account",
        kind="model",
        provider_id="slow",
        implementation=Slow(),
    )
    adapter = create_llm_adapter(
        provider_type="slow", api_key="", model="test", provider_registry=registry
    )
    with pytest.raises(asyncio.TimeoutError):
        await adapter.stream_tool_response(messages=[], timeout_seconds=0.01)
    assert closed.is_set()


def test_provider_owner_disposal_and_revocation_are_live(providers):
    registry, connections = providers
    provider = ModelProvider()
    dispose = registry.register(
        plugin_id="test",
        connection_id="account",
        kind="model",
        provider_id="model",
        implementation=provider,
    )
    with pytest.raises(ValueError, match="already registered"):
        registry.register(
            plugin_id="test",
            connection_id="account",
            kind="model",
            provider_id="model",
            implementation=ModelProvider(),
        )
    dispose()
    registry.register(
        plugin_id="test",
        connection_id="account",
        kind="model",
        provider_id="model",
        implementation=provider,
    )
    dispose()
    assert registry.get("model", "model") is provider
    connections["account"] = connections["account"].model_copy(
        update={"enabled": False}
    )
    assert registry.names("model") == []


@pytest.mark.asyncio
async def test_persisted_selection_resolves_plugin_provider_without_native_credentials(
    providers,
):
    registry, connections = providers
    provider = ModelProvider()
    registry.register(
        plugin_id="test",
        connection_id="account",
        kind="model",
        provider_id="account:model",
        implementation=provider,
    )
    config = AppConfig()
    config.llm.selections["core"] = LLMSelectionSettings(
        provider_id="account:model", model="test-model"
    )
    pool = create_scenario_llm_pool(config, provider_registry=registry)
    assert await pool.get(LLMScenario.CORE).chat([]) == "Hello"
    config.llm.selections["embedding"] = config.llm.selections["core"]
    with pytest.raises(ValueError, match="embeddings"):
        pool.get(LLMScenario.EMBEDDING)
    connections["account"] = connections["account"].model_copy(
        update={"enabled": False}
    )
    with pytest.raises(ValueError, match="unknown provider"):
        pool.get(LLMScenario.CORE)


@pytest.mark.asyncio
async def test_external_agent_service_resolves_sdk_adapter_and_cancels(
    providers, tmp_path
):
    registry, _ = providers
    started, closed = asyncio.Event(), asyncio.Event()

    class Agent:
        async def invoke(self, request):
            return ExternalAgentResult(status="succeeded", summary="Done")

        async def stream(self, request):
            assert isinstance(request, ExternalAgentRequest)
            assert request.identity.connection_id == "account"
            try:
                yield ExternalAgentEvent(
                    kind="assistant_text", payload={"text": "Working"}
                )
                started.set()
                await asyncio.Event().wait()
            finally:
                closed.set()

    registry.register(
        plugin_id="test",
        connection_id="account",
        kind="external_agent",
        provider_id="account:coder",
        implementation=Agent(),
    )
    req = DelegateRequest(
        delegation_id="a" * 32,
        session_id="session1",
        turn_id="turn1",
        adapter="account:coder",
        prompt="Work",
        workspace_root=str(tmp_path),
        constraints=DelegateConstraints(),
        timeout_s=10,
    )
    service = CodeAgentService(provider_registry=registry)
    adapter, binary, error = service._resolve_adapter(req)
    assert error is None
    token, emit = CancelToken(), AsyncMock()
    task = asyncio.create_task(
        adapter.run(
            req,
            cwd=tmp_path,
            bundle_dir=tmp_path,
            stdout_path=tmp_path / "stdout",
            stderr_path=tmp_path / "stderr",
            on_event=emit,
            cancel_token=token,
            binary_path=binary,
        )
    )
    await started.wait()
    token.cancel()
    result = await asyncio.wait_for(task, 1)
    assert result.cancelled and closed.is_set()
    assert emit.await_args.args[0].kind == "assistant_text"
