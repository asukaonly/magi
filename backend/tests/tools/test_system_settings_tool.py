"""
Tests for the refactored system-settings routing behavior.
"""

from types import MethodType, SimpleNamespace

import pytest

from magi.config.models import AppConfig, ProxyType
from magi.tools.builtin.system_settings_tool import SystemSettingsTool
from magi.tools.builtin.weather_tool import WeatherTool
from magi.tools.builtin.web_fetch_tool import WebFetchTool
from magi.tools.builtin.web_search_tool import WebSearchTool
from magi.tools.registry import tool_registry
from magi.tools.schema import ToolExecutionContext, ToolResult, ToolErrorCode


def _context() -> ToolExecutionContext:
    return ToolExecutionContext(agent_id="test-agent")


def _ensure_tool_registered(name: str, tool_class) -> None:
    if tool_registry.get_tool(name) is None:
        tool_registry.register(tool_class)


@pytest.mark.asyncio
async def test_list_contains_app_and_tool_paths():
    _ensure_tool_registered("web-search", WebSearchTool)
    _ensure_tool_registered("web-fetch", WebFetchTool)
    _ensure_tool_registered("weather", WeatherTool)
    tool = SystemSettingsTool()
    result = await tool.execute({"action": "list"}, _context())

    assert result.success is True
    assert "app.llm.timeout" in result.data["available_paths"]
    assert "tool.web-search.default_provider" in result.data["available_paths"]
    assert "tool.web-fetch.default_provider" in result.data["available_paths"]
    assert "tool.weather.providers.{provider}.api_key" in result.data["available_paths"]


@pytest.mark.asyncio
async def test_set_app_path_uses_save_config_with_type_conversion(monkeypatch):
    tool = SystemSettingsTool()
    captured = {}
    refreshed = []

    fake_config = SimpleNamespace(
        llm=SimpleNamespace(timeout=60),
    )

    def fake_get_config():
        return fake_config

    def fake_save_config(updates):
        captured.update(updates)
        return True

    monkeypatch.setattr("magi.tools.builtin.system_settings_tool.get_config", fake_get_config)
    monkeypatch.setattr("magi.tools.builtin.system_settings_tool.save_config", fake_save_config)
    monkeypatch.setattr(
        "magi.tools.builtin.system_settings_tool.refresh_runtime_llm_config",
        lambda config: refreshed.append(config),
    )

    result = await tool.execute(
        {"action": "set", "path": "app.llm.timeout", "value": "120"},
        _context(),
    )

    assert result.success is True
    assert captured == {"llm.timeout": 120}
    assert refreshed == [fake_config]


def _local_embedding_settings_config(*, model_id: str = "model-a"):
    return SimpleNamespace(
        agent=SimpleNamespace(
            memory=SimpleNamespace(
                db_path="memory.db",
                embedding=SimpleNamespace(
                    backend="sqlite_vec",
                    mode="local",
                    local=SimpleNamespace(
                        model_source="managed",
                        managed_model_id=model_id,
                        model_dir_path="",
                    ),
                ),
                l1=SimpleNamespace(enabled=True, vectors_enabled=True),
                l2=SimpleNamespace(enabled=True, vectors_enabled=True),
                l3=SimpleNamespace(enabled=True, vectors_enabled=True),
                l4=SimpleNamespace(enabled=True, vectors_enabled=True),
            )
        ),
        llm=SimpleNamespace(selections={}, providers={}),
    )


@pytest.mark.asyncio
async def test_set_embedding_app_path_stops_rebuild_before_save_and_resumes_after_refresh(
    monkeypatch,
):
    tool = SystemSettingsTool()
    current = _local_embedding_settings_config()
    calls = []

    class RebuildManager:
        async def pause_starts_and_cancel_all(self):
            calls.append("pause")
            return 1

        async def resume_starts(self):
            calls.append("resume")

    monkeypatch.setattr(
        "magi.tools.builtin.system_settings_tool.get_config",
        lambda: current,
    )
    monkeypatch.setattr(
        "magi.tools.builtin.system_settings_tool.get_embedding_rebuild_manager",
        lambda: RebuildManager(),
    )
    monkeypatch.setattr(
        "magi.tools.builtin.system_settings_tool.save_config",
        lambda updates: calls.append(("save", updates)) or True,
    )
    monkeypatch.setattr(
        "magi.tools.builtin.system_settings_tool.refresh_runtime_llm_config",
        lambda _config: calls.append("refresh"),
    )

    result = await tool.execute(
        {
            "action": "set",
            "path": "app.agent.memory.embedding.local.managed_model_id",
            "value": "model-b",
        },
        _context(),
    )

    assert result.success is True
    assert calls == [
        "pause",
        (
            "save",
            {"agent.memory.embedding.local.managed_model_id": "model-b"},
        ),
        "refresh",
        "resume",
    ]


@pytest.mark.asyncio
async def test_set_embedding_app_path_resumes_rebuild_when_save_fails(monkeypatch):
    tool = SystemSettingsTool()
    current = _local_embedding_settings_config()
    calls = []

    class RebuildManager:
        async def pause_starts_and_cancel_all(self):
            calls.append("pause")
            return 1

        async def resume_starts(self):
            calls.append("resume")

    monkeypatch.setattr(
        "magi.tools.builtin.system_settings_tool.get_config",
        lambda: current,
    )
    monkeypatch.setattr(
        "magi.tools.builtin.system_settings_tool.get_embedding_rebuild_manager",
        lambda: RebuildManager(),
    )
    monkeypatch.setattr(
        "magi.tools.builtin.system_settings_tool.save_config",
        lambda _updates: calls.append("save") or False,
    )
    monkeypatch.setattr(
        "magi.tools.builtin.system_settings_tool.refresh_runtime_llm_config",
        lambda _config: calls.append("refresh"),
    )

    result = await tool.execute(
        {
            "action": "set",
            "path": "app.agent.memory.embedding.local.managed_model_id",
            "value": "model-b",
        },
        _context(),
    )

    assert result.success is False
    assert result.error_code == ToolErrorCode.SAVE_FAILED.value
    assert calls == ["pause", "save", "resume"]


@pytest.mark.asyncio
async def test_set_app_enum_path_rejects_invalid_value(monkeypatch):
    tool = SystemSettingsTool()

    fake_config = SimpleNamespace(
        network=SimpleNamespace(proxy_type=ProxyType.HTTP),
    )

    def fake_get_config():
        return fake_config

    def fake_save_config(_updates):
        raise AssertionError("save_config should not be called for invalid enum values")

    monkeypatch.setattr("magi.tools.builtin.system_settings_tool.get_config", fake_get_config)
    monkeypatch.setattr("magi.tools.builtin.system_settings_tool.save_config", fake_save_config)

    result = await tool.execute(
        {"action": "set", "path": "app.network.proxy_type", "value": "none"},
        _context(),
    )

    assert result.success is False
    assert result.error_code == ToolErrorCode.TYPE_ERROR.value
    assert "Type conversion failed" in result.error


@pytest.mark.parametrize(
    "tool_name,tool_class,setting_path,value",
    [
        ("web-search", WebSearchTool, "providers.brave.api_key", "test-key"),
        ("web-fetch", WebFetchTool, "default_provider", "browser"),
    ],
)
@pytest.mark.asyncio
async def test_set_tool_path_routes_to_tool_update(
    monkeypatch, tool_name, tool_class, setting_path, value
):
    _ensure_tool_registered(tool_name, tool_class)
    target = tool_registry.get_tool(tool_name)
    called = []
    context = _context()

    async def fake_update_config(self, path, value, context):
        called.append((self, path, value, context))
        return ToolResult(success=True, data={"ok": True})

    monkeypatch.setattr(target, "update_config", MethodType(fake_update_config, target))
    result = await SystemSettingsTool().execute(
        {"action": "set", "path": f"tool.{tool_name}.{setting_path}", "value": value},
        context,
    )
    assert result.success is True
    assert called == [(target, setting_path, value, context)]


@pytest.mark.parametrize(
    "secret,expected_value,configured",
    [
        pytest.param("canary-do-not-return-this-key", "***MASKED***", True, id="configured"),
        pytest.param(None, None, False, id="missing"),
        pytest.param("", None, False, id="empty"),
    ],
)
@pytest.mark.asyncio
async def test_get_sensitive_path_masks_configured_secret(
    monkeypatch, secret, expected_value, configured
):
    config = AppConfig()
    config.tools.web_search.providers["brave"].api_key = secret
    monkeypatch.setattr("magi.tools.builtin.system_settings_tool.get_config", lambda: config)
    result = await SystemSettingsTool().execute(
        {"action": "get", "path": "tool.web-search.providers.brave.api_key"},
        _context(),
    )
    assert result.success is True
    assert result.data["sensitive"] is True
    assert result.data["configured"] is configured
    assert result.data["value"] == expected_value
    assert "canary-do-not-return-this-key" not in str(result)
    assert config.tools.web_search.providers["brave"].api_key == secret


@pytest.mark.parametrize("tool_class", [WeatherTool, WebSearchTool, WebFetchTool])
def test_public_tool_schema_excludes_configuration_and_secrets(tool_class):
    parameters = {item.name for item in tool_class().get_schema().parameters}
    assert parameters
    assert parameters.isdisjoint({"action", "config_action", "api_key"})
