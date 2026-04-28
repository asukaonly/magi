from __future__ import annotations

from pathlib import Path

import pytest

from magi.config.models import AppConfig, PluginSettings
from magi.plugins import Plugin
from magi.plugins.manager import PluginManager, build_plugin_runtime
from magi.plugins.sensors import SensorRegistry
from magi.tools.registry import ToolRegistry, tool_registry as shared_tool_registry
from magi_plugin_sdk import TemporalSummarySourceFeatures


def _apply_updates(config: AppConfig, updates: dict[str, object]) -> None:
    for path, value in updates.items():
        current = config
        parts = path.split(".")
        for part in parts[:-1]:
            if hasattr(current, part):
                current = getattr(current, part)
                continue
            if isinstance(current, dict):
                current = current.setdefault(part, {})
                continue
            raise KeyError(part)
        last = parts[-1]
        if isinstance(current, dict):
            current[last] = value
        else:
            setattr(current, last, value)


def _write_external_tool_plugin(base: Path) -> None:
    plugin_dir = base / "external-tool"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.toml").write_text(
        """
[plugin]
id = "external-tool"
name = "External Tool"
version = "1.0.0"
description = "External test plugin"
author = "Test"
entry_module = "plugin"
entry_class = "ExternalToolPlugin"
official = false
contribution_types = ["tool"]
""".strip(),
        encoding="utf-8",
    )
    (plugin_dir / "plugin.py").write_text(
        """from magi_plugin_sdk import Plugin
from magi_plugin_sdk.tools import Tool, ToolSchema, ToolExecutionContext, ToolResult

class ExternalHelloTool(Tool):
    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="external-hello",
            description="Say hello",
            category="test",
        )

    async def execute(self, parameters, context: ToolExecutionContext) -> ToolResult:
        return ToolResult(success=True, data={"message": "hello"})

class ExternalToolPlugin(Plugin):
    def get_tools(self):
        return [ExternalHelloTool]
""".strip(),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_plugin_manager_discovers_external_plugins_and_loads_enabled_tools(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_external_tool_plugin(tmp_path)
    config = AppConfig()
    config.plugins.packages["external-tool"] = PluginSettings(
        enabled=True,
        trusted=True,
        source="external",
        settings={},
    )
    tool_registry = ToolRegistry()

    monkeypatch.setattr("magi.plugins.manager.get_config", lambda: config)
    monkeypatch.setattr("magi.plugins.manager.save_config", lambda updates: _apply_updates(config, updates) or True)

    manager = PluginManager(
        tool_registry=tool_registry,
        sensor_registry=SensorRegistry(),
        search_paths=[tmp_path],
    )

    discovered = manager.scan(persist_discovery=True)
    assert [item.manifest.plugin_id for item in discovered] == ["external-tool"]

    manager.activate_enabled_plugins()
    assert "external-hello" in tool_registry.list_tools()

    manager.disable_plugin("external-tool")
    assert "external-hello" not in tool_registry.list_tools()


def test_plugin_manager_persists_newly_discovered_plugins_as_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_external_tool_plugin(tmp_path)
    config = AppConfig()
    tool_registry = ToolRegistry()

    monkeypatch.setattr("magi.plugins.manager.get_config", lambda: config)
    monkeypatch.setattr("magi.plugins.manager.save_config", lambda updates: _apply_updates(config, updates) or True)

    manager = PluginManager(
        tool_registry=tool_registry,
        sensor_registry=SensorRegistry(),
        search_paths=[tmp_path],
    )

    packages = manager.scan(persist_discovery=True)
    assert packages[0].enabled is False
    package_settings = config.plugins.packages["external-tool"]
    if isinstance(package_settings, dict):
        assert package_settings["enabled"] is False
        assert package_settings["trusted"] is False
    else:
        assert package_settings.enabled is False
        assert package_settings.trusted is False


def test_core_tools_plugin_registers_memory_query_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    config = AppConfig()
    config.plugins.packages["core-tools"] = PluginSettings(
        enabled=True,
        trusted=True,
        source="builtin",
        settings={},
    )
    tool_registry = ToolRegistry()

    monkeypatch.setattr("magi.plugins.manager.get_config", lambda: config)
    monkeypatch.setattr("magi.plugins.manager.save_config", lambda updates: _apply_updates(config, updates) or True)

    builtin_plugins_root = Path(__file__).resolve().parents[3] / "plugins"
    manager = PluginManager(
        tool_registry=tool_registry,
        sensor_registry=SensorRegistry(),

        search_paths=[builtin_plugins_root],
    )

    packages = manager.scan(persist_discovery=False)
    assert any(item.manifest.plugin_id == "core-tools" for item in packages)

    manager.activate_enabled_plugins()

    assert "memory_query" in tool_registry.list_tools()


def test_build_plugin_runtime_uses_shared_tool_registry_by_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = AppConfig()

    monkeypatch.setattr("magi.plugins.manager.get_config", lambda: config)
    monkeypatch.setattr("magi.plugins.manager.save_config", lambda updates: _apply_updates(config, updates) or True)
    monkeypatch.setattr("magi.plugins.manager._resolve_search_paths", lambda: [tmp_path])

    bindings = build_plugin_runtime(
        sensor_registry=SensorRegistry(),
    )

    assert bindings.plugin_manager._tool_registry is shared_tool_registry


def test_plugin_manager_collects_temporal_summary_features_from_loaded_plugins() -> None:
    class ChromeFeaturePlugin(Plugin):
        def build_temporal_summary_features(self, *, source_type, events, summary_category, period_start, period_end):  # type: ignore[no-untyped-def]
            _ = summary_category, period_start, period_end
            assert source_type == "chrome_history"
            assert len(events) == 3
            return {
                "feature_type": "chrome_history",
                "event_count": 3,
                "visit_count": 4,
                "unique_domain_count": 2,
                "focus_domain": "openai.com",
                "focus_share": 2 / 3,
                "session_count": 1,
                "top_domains": [
                    {"domain": "openai.com", "count": 2},
                    {"domain": "github.com", "count": 1},
                ],
                "revisit_domains": ["openai.com"],
                "summary_lines": [
                    "Browsing concentrated heavily on openai.com.",
                    "Repeated visits clustered around openai.com.",
                    "Browsing stayed within a small set of sites.",
                ],
            }

    manager = PluginManager(
        tool_registry=ToolRegistry(),
        sensor_registry=SensorRegistry(),
        search_paths=[],
    )
    manager._plugin_instances["chrome-feature"] = ChromeFeaturePlugin()

    features = manager.build_temporal_summary_features(
        events=[
            {
                "event_id": "evt-1",
                "source": "chrome_history",
                "content": "OpenAI docs",
                "metadata_json": {
                    "timeline": {
                        "provenance": {
                            "domain": "openai.com",
                            "merged_visit_count": 2,
                        }
                    }
                },
            },
            {
                "event_id": "evt-2",
                "source": "chrome_history",
                "content": "GitHub issues",
                "metadata_json": {
                    "timeline": {
                        "provenance": {
                            "domain": "github.com",
                            "merged_visit_count": 1,
                        }
                    }
                },
            },
            {
                "event_id": "evt-3",
                "source": "chrome_history",
                "content": "OpenAI pricing",
                "metadata_json": {
                    "timeline": {
                        "provenance": {
                            "domain": "openai.com",
                            "merged_visit_count": 1,
                        }
                    }
                },
            },
        ],
        summary_category="day",
        period_start=1710000000.0,
        period_end=1710003600.0,
    )

    assert features == {
        "chrome_history": {
            "feature_type": "chrome_history",
            "event_count": 3,
            "visit_count": 4,
            "unique_domain_count": 2,
            "focus_domain": "openai.com",
            "focus_share": pytest.approx(2 / 3, rel=1e-3),
            "session_count": 1,
            "top_domains": [
                {"domain": "openai.com", "count": 2},
                {"domain": "github.com", "count": 1},
            ],
            "revisit_domains": ["openai.com"],
            "summary_lines": [
                "Browsing concentrated heavily on openai.com.",
                "Repeated visits clustered around openai.com.",
                "Browsing stayed within a small set of sites.",
            ],
        }
    }


def test_plugin_manager_passes_temporal_feature_budget_to_new_hooks() -> None:
    class BudgetAwarePlugin(Plugin):
        def build_temporal_summary_features(self, *, source_type, events, summary_category, period_start, period_end, budget=None):  # type: ignore[no-untyped-def]
            _ = summary_category, period_start, period_end
            assert source_type == "music"
            assert len(events) == 1
            assert budget is not None
            return TemporalSummarySourceFeatures(
                source_type=source_type,
                total_event_count=budget.total_event_count,
                covered_event_count=budget.available_event_count,
                omitted_event_count=budget.omitted_event_count,
                summary_lines=["Music listening was compacted for L3."],
            )

    manager = PluginManager(
        tool_registry=ToolRegistry(),
        sensor_registry=SensorRegistry(),
        search_paths=[],
    )
    manager._plugin_instances["budget-aware"] = BudgetAwarePlugin()

    features = manager.build_temporal_summary_features(
        events=[{"event_id": "evt-1", "source": "music", "content": "song"}],
        summary_category="day",
        period_start=1.0,
        period_end=2.0,
        feature_budgets={
            "music": {
                "source_type": "music",
                "total_event_count": 10,
                "available_event_count": 4,
                "selected_event_count": 1,
                "omitted_event_count": 6,
            }
        },
    )

    assert features["music"]["total_event_count"] == 10
    assert features["music"]["covered_event_count"] == 4
    assert features["music"]["omitted_event_count"] == 6
