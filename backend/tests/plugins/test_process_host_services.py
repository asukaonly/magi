"""Exercise public typed host services through an actual external worker."""

import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from magi.core.tool_capabilities import AskOutcome, ToolCapabilities
from magi.plugins.operations import PluginOperationRegistry
from magi.plugins.process_runtime import ProcessPluginProxy, ProcessLimits
from magi.agent.background import BackgroundTaskStore
from magi.tools.registry import ToolRegistry
from test_process_runtime import PLUGIN, plugin_setup as plugin_setup
from test_public_host_services import installed_authority, memory_port


MEMORY_TOOL = '''
from magi_plugin_sdk import MemorySearchRequest
class EchoTool(Tool):
    def _init_schema(self):
        self.schema = ToolSchema(name="memory_probe", description="Memory", category="test",
            effect_class="read_only", effect_replay_policy="read_only")
    async def execute(self, parameters, context):
        if "memory.search" not in context.host.permitted_methods:
            return ToolResult(success=True, data={"granted":False})
        result = await context.host.memory_search(MemorySearchRequest(query="Fridays", limit=1))
        return ToolResult(success=True, data={"granted":True, "recall":result.model_dump(mode="json"),
            "env":context.env_vars, "has_internal_ports":hasattr(context, "capabilities")})
'''


@pytest.mark.asyncio
@pytest.mark.parametrize("consented", [True, False])
async def test_installed_consent_and_governed_recall_cross_real_worker(
    plugin_setup, runtime_paths_with_schema, consented,
):
    manifest, _connection, plugin_context = plugin_setup
    ctx, config, _, authority, _ = installed_authority(mode="trusted_process")
    if not consented:
        config.consented_capabilities = []
    port = memory_port()
    ctx.capabilities = ToolCapabilities(memory_query=port)
    manifest = manifest.model_copy(update={"plugin_id": ctx.connection.plugin_id})
    plugin_context = replace(plugin_context, connection=ctx.connection)
    Path(manifest.plugin_dir, "plugin.py").write_text(PLUGIN + MEMORY_TOOL)
    proxy = ProcessPluginProxy(manifest, ctx.connection, plugin_context)
    tools = ToolRegistry()
    tools.bind_tool_effect_ledger(BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path)))
    registry = PluginOperationRegistry(tools, get_connection=lambda _: ctx.connection, authorize=authority)
    registry.register_tool(plugin_id=manifest.plugin_id, connection_id=ctx.connection.connection_id,
                           tool_class=proxy.get_tools()[0])
    try:
        result = await registry.invoke(ctx.connection.connection_id, "memory_probe", {},
                                       identity=ctx.invocation, context=ctx)
        assert result.status == "succeeded", result
        assert result.value["granted"] is consented
        assert port._service.query.await_count == int(consented)
        if consented:
            assert result.value["recall"]["findings"][0]["statement"] == "The user said: only on Fridays."
            assert result.value["env"] == {} and result.value["has_internal_ports"] is False
            assert "/host/private" not in str(result.value)
    finally:
        await proxy.shutdown()


@pytest.mark.asyncio
async def test_interaction_uses_invocation_deadline_and_original_identity(plugin_setup):
    manifest, _connection, plugin_context = plugin_setup
    ctx, _, _, _, _ = installed_authority(mode="trusted_process")
    manifest = manifest.model_copy(update={"plugin_id": ctx.connection.plugin_id})
    plugin_context = replace(plugin_context, connection=ctx.connection)
    Path(manifest.plugin_dir, "plugin.py").write_text(PLUGIN + '''
from magi_plugin_sdk import AskUserRequest
class EchoTool(Tool):
    def _init_schema(self):
        self.schema = ToolSchema(name="ask_probe", description="Ask", category="test", timeout=90,
            effect_class="external_write", effect_replay_policy="non_idempotent")
    async def execute(self, parameters, context):
        reply = await context.host.ask_user(AskUserRequest(question="Which day?", timeout_seconds=1.0))
        return ToolResult(success=True, data=reply.model_dump(mode="json"))
''')

    async def answer(**kwargs):
        await asyncio.sleep(0.15)
        return AskOutcome(answered=True, answer="Only Fridays.", resolution="user", timed_out=False)

    ask = AsyncMock(side_effect=answer)
    ctx.capabilities = ToolCapabilities(interaction=SimpleNamespace(ask=ask))
    proxy = ProcessPluginProxy(manifest, ctx.connection, plugin_context,
                               limits=ProcessLimits(callback_timeout=0.05))
    try:
        result = await proxy.get_tools()[0]().execute({}, ctx)
        assert result.success and result.data["answer"] == "Only Fridays."
        assert ask.await_args.kwargs["user_id"] == "local_user"
        assert ask.await_args.kwargs["session_id"] == "session"
        assert ask.await_args.kwargs["turn_id"] == "turn"
    finally:
        await proxy.shutdown()
