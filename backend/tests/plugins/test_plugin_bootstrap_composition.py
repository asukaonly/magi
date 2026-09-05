"""Actual plugin startup shares its early hook and skill registries with later modules."""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

from dependency_injector import providers
import pytest

from magi.agent.background import BackgroundTaskStore
from magi.bootstrap.context import RuntimeBootstrapContext
from magi.config.models import AppConfig, PluginSettings
from magi.hooks.lifecycle import HooksModule
from magi.hooks.registry import HookRegistry
from magi.plugins.connections import PluginConnectionStore
from magi.plugins.discovery import load_plugin_manifest
from magi.plugins.lifecycle import PluginSystemModule
from magi.plugins.operation_authorization import build_host_invocation
from magi.plugins.process_runtime import ProcessPluginProxy
from magi.skills.indexer import SkillIndexer
from magi.skills.lifecycle import SkillsModule
from magi.tools.registry import ToolRegistry
from magi_plugin_sdk.hooks import HookContext, HookDecision, HookEventType, HookOutcome


MANIFEST = '''
[plugin]
id = "bootstrap-test"
name = "Bootstrap test"
version = "0.2.0"
protocol_version = 2
min_sdk_version = "0.2.0"
execution_mode = "trusted_process"
entry_class = "BootstrapPlugin"
contribution_types = ["hook", "skill"]

[[plugin.settings_actions]]
action_id = "login"
label = "Login"
requires_enabled = false
'''

PLUGIN = '''
import os
from pathlib import Path
from magi_plugin_sdk import Plugin
from magi_plugin_sdk.hooks import HookEventType, HookDecision

class BootstrapPlugin(Plugin):
    def get_hooks(self):
        async def on_prompt(context):
            return HookDecision.inject(f"worker:{os.getpid()}:{self.connection_id}")
        return [(HookEventType.USER_PROMPT_SUBMIT, on_prompt, None)]
    def get_skills(self):
        return [("summarize", Path(self.plugin_dir) / "skills" / "summarize")]
    async def start_settings_action(self, action_id, *, session_id, field_values=None):
        return {"status": "pending", "data": {"pid": os.getpid(), "session": session_id}}
'''


@pytest.fixture
def bootstrap(tmp_path, monkeypatch, runtime_paths_with_schema):
    package = tmp_path / "package"
    skill = package / "skills" / "summarize"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: summarize\ndescription: Summarize notes\n---\nSummarize $@.\n")
    path = package / "plugin.toml"
    path.write_text(MANIFEST)
    (package / "plugin.py").write_text(PLUGIN)
    manifest = load_plugin_manifest(path, source="external")
    config = AppConfig()
    config.features.enable_skills = True
    config.plugins.packages[manifest.plugin_id] = PluginSettings(
        trusted=True, source="external", manifest_path=str(path), consented_capabilities=[])
    monkeypatch.setattr("magi.config.get_config", lambda: config)
    monkeypatch.setattr("magi.plugins.manager.get_config", lambda: config)
    monkeypatch.setattr("magi.skills.service_access.get_config", lambda: config)
    monkeypatch.setattr("magi.plugins.manager._resolve_search_paths", lambda: [package])
    monkeypatch.setattr("magi.plugins.connections.get_runtime_paths", lambda: runtime_paths_with_schema)
    monkeypatch.setattr(SkillIndexer, "SKILL_LOCATIONS", [tmp_path / "empty-skills"])
    container = SimpleNamespace(hook_registry=providers.Dependency(), hook_gateway=providers.Dependency())
    monkeypatch.setattr("magi.core.container.get_container", lambda: container)
    user_hook_loader = AsyncMock()
    monkeypatch.setattr("magi.hooks.lifecycle.load_user_hook_handlers", user_hook_loader)

    context = RuntimeBootstrapContext()
    context.core.runtime_paths = runtime_paths_with_schema
    context.core.config = config
    context.llm.llm_adapter = object()
    context.llm.scenario_llm_pool = SimpleNamespace(resolve=lambda *_: None)
    context.runtime_commands.runtime_command_queue = SimpleNamespace(
        read_full_user_content_clear_state=AsyncMock(return_value=SimpleNamespace(status="idle", transaction_id=None)),
        read_current_clear_generation=AsyncMock(return_value=0))
    tools = ToolRegistry()
    tools.bind_tool_effect_ledger(BackgroundTaskStore(
        db_path=str(runtime_paths_with_schema.background_tasks_db_path)))
    module = PluginSystemModule(context, tool_registry=tools, request_sensor_schedule_refresh=lambda: None)
    hooks = HooksModule(context)
    skills = SkillsModule(context, tools, orchestrator_factory=lambda **_: None,
                          agent_run_request_factory=lambda **_: None)
    store = PluginConnectionStore(runtime_paths=runtime_paths_with_schema,
                                  require_package=lambda _: manifest, authorize_enable=lambda _: True)
    yield SimpleNamespace(context=context, tools=tools, plugins=module, hooks=hooks, skills=skills,
                          store=store, container=container, user_hook_loader=user_hook_loader)
    asyncio.run(module.shutdown())
    asyncio.run(hooks.shutdown())
    asyncio.run(skills.shutdown())


@pytest.mark.asyncio
async def test_early_external_hook_and_skill_survive_later_modules_and_owner_unload(bootstrap):
    app = bootstrap
    connection = app.store.create("bootstrap-test", display_name="Account", enabled=True)
    existing_hooks = HookRegistry()

    async def host_hook(context):
        return HookDecision.inject("host-before-plugin")

    existing_hooks.register(HookEventType.USER_PROMPT_SUBMIT, host_hook)
    app.context.hooks.registry = existing_hooks
    await app.plugins.init()
    manager = app.context.plugins.plugin_manager
    worker = manager.get_connection_plugin(connection.connection_id)
    assert isinstance(worker, ProcessPluginProxy), manager.get_package("bootstrap-test").last_error
    assert app.context.hooks.registry is existing_hooks
    assert existing_hooks.total() == 2
    skill_name = f"{connection.connection_id}:summarize"
    indexer = app.context.skills.skill_indexer
    loader = app.context.skills.skill_loader
    metadata = indexer.get_metadata(skill_name)
    assert metadata is not None
    assert app.tools.is_skill(skill_name)
    assert "Summarize" in loader.load_skill(skill_name).prompt_template

    await app.hooks.init()
    await app.skills.init()
    assert app.context.hooks.registry is existing_hooks
    assert app.container.hook_registry() is existing_hooks
    assert app.container.hook_gateway() is app.context.hooks.gateway
    app.user_hook_loader.assert_awaited_once_with(existing_hooks)
    assert app.context.skills.skill_indexer is indexer
    assert app.context.skills.skill_loader is loader
    assert app.context.skills.skill_runner.loader is loader
    assert indexer.get_metadata(skill_name) is metadata
    assert app.tools.is_skill(skill_name)

    decision = await app.context.hooks.gateway.dispatch(HookContext(
        event_type=HookEventType.USER_PROMPT_SUBMIT, user_message="Test"))
    assert decision.outcome == HookOutcome.INJECT_CONTEXT
    assert "host-before-plugin" in decision.additional_context
    remote = next(line for line in decision.additional_context.splitlines() if line.startswith("worker:"))
    _, pid, remote_connection = remote.split(":", 2)
    assert int(pid) != os.getpid()
    assert remote_connection == connection.connection_id
    result = await app.context.skills.skill_runner.execute(skill_name, arguments=["fresh notes"])
    assert result.success
    assert "Summarize fresh notes." in result.content
    app.tools.refresh_skills()
    assert app.tools.is_skill(skill_name)

    await manager.unload_connection_async(connection.connection_id)
    assert worker.diagnostics["exit_code"] is not None
    assert not app.tools.is_skill(skill_name)
    assert loader.load_skill(skill_name) is None
    assert indexer.get_metadata(skill_name) is None
    assert existing_hooks.total() == 1
    decision = await app.context.hooks.gateway.dispatch(HookContext(event_type=HookEventType.USER_PROMPT_SUBMIT))
    assert decision.additional_context == "host-before-plugin"


@pytest.mark.asyncio
async def test_actual_bootstrap_authorizer_exposes_disabled_setup_actions_without_general_contributions(bootstrap):
    app = bootstrap
    connection = app.store.create("bootstrap-test", display_name="Login account")
    await app.plugins.init()
    manager = app.context.plugins.plugin_manager
    assert manager.get_connection_plugin(connection.connection_id) is None
    started = await manager.start_plugin_settings_action(connection.connection_id, "login",
        identity=build_host_invocation(connection, trigger="user"))
    assert started.result.status == "pending", started.result
    assert started.result.data["pid"] != os.getpid()
    assert manager.get_connection_plugin(connection.connection_id) is None
    assert app.context.hooks.registry.total() == 0
    assert not app.tools.is_skill(f"{connection.connection_id}:summarize")
    assert app.tools.list_tools() == []
