from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from magi.config.models import AppConfig, PluginSettings
from magi.plugins.actions import ActionRegistry
from magi.plugins.manager import PluginManager
from magi.plugins.sensors import SensorRegistry
from magi.timeline import SensorSyncContext
from magi.tools.registry import ToolRegistry
from magi.utils.runtime import Runtimepaths


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


def _create_history_db(root: Path) -> Path:
    profile_dir = root / "Default"
    profile_dir.mkdir(parents=True, exist_ok=True)
    db_path = profile_dir / "History"
    connection = sqlite3.connect(db_path)
    try:
        connection.executescript(
            """
            CREATE TABLE urls (
                id INTEGER PRIMARY KEY,
                url TEXT,
                title TEXT,
                visit_count INTEGER DEFAULT 0
            );
            CREATE TABLE visits (
                id INTEGER PRIMARY KEY,
                url INTEGER,
                visit_time INTEGER,
                from_visit INTEGER DEFAULT 0,
                transition INTEGER DEFAULT 0
            );
            """
        )
        connection.execute(
            "INSERT INTO urls (id, url, title, visit_count) VALUES (?, ?, ?, ?)",
            (1, "https://github.com/", "GitHub", 1),
        )
        connection.execute(
            "INSERT INTO urls (id, url, title, visit_count) VALUES (?, ?, ?, ?)",
            (2, "https://github.com/openai/openai-python", "openai/openai-python", 3),
        )
        connection.execute(
            "INSERT INTO urls (id, url, title, visit_count) VALUES (?, ?, ?, ?)",
            (3, "https://accounts.example.com/login", "Sign in", 4),
        )
        connection.execute(
            "INSERT INTO visits (id, url, visit_time, from_visit, transition) VALUES (?, ?, ?, ?, ?)",
            (101, 1, 13285468800000000, 0, 0),
        )
        connection.execute(
            "INSERT INTO visits (id, url, visit_time, from_visit, transition) VALUES (?, ?, ?, ?, ?)",
            (102, 2, 13285469400000000, 101, 0),
        )
        connection.execute(
            "INSERT INTO visits (id, url, visit_time, from_visit, transition) VALUES (?, ?, ?, ?, ?)",
            (103, 3, 13285470000000000, 102, 0),
        )
        connection.commit()
    finally:
        connection.close()
    return root


def _plugin_root() -> Path:
    return Path(__file__).resolve().parents[2] / "plugins"


def _build_manager(monkeypatch: pytest.MonkeyPatch, config: AppConfig) -> tuple[PluginManager, SensorRegistry]:
    sensor_registry = SensorRegistry()
    monkeypatch.setattr("magi.plugins.manager.get_config", lambda: config)
    monkeypatch.setattr("magi.plugins.manager.save_config", lambda updates: _apply_updates(config, updates) or True)
    manager = PluginManager(
        tool_registry=ToolRegistry(),
        sensor_registry=sensor_registry,
        action_registry=ActionRegistry(),
        search_paths=[_plugin_root()],
    )
    return manager, sensor_registry


def test_chrome_history_plugin_is_discovered_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    config = AppConfig()
    manager, _ = _build_manager(monkeypatch, config)

    packages = manager.scan(persist_discovery=False)
    chrome_package = next(item for item in packages if item.manifest.plugin_id == "chrome-history")

    assert chrome_package.enabled is False
    assert chrome_package.manifest.source == "builtin"
    assert chrome_package.manifest.official is False


@pytest.mark.asyncio
async def test_chrome_history_sensor_collects_events_and_relations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    chrome_root = _create_history_db(tmp_path / "chrome")
    config = AppConfig()
    config.plugins.packages["chrome-history"] = PluginSettings(
        enabled=True,
        trusted=True,
        source="builtin",
        settings={
            "sensors": {
                "chrome_history": {
                    "enabled": True,
                    "source_path": str(chrome_root),
                    "profile": "Default",
                    "sync_mode": "manual",
                    "sync_interval_minutes": 30,
                    "lookback_hours": 48,
                    "max_items_per_sync": 50,
                    "fetch_page_content": False,
                    "edge_whitelist": ["VISITED", "VIEWED"],
                }
            }
        },
    )
    manager, sensor_registry = _build_manager(monkeypatch, config)

    packages = manager.scan(persist_discovery=False)
    assert any(item.manifest.plugin_id == "chrome-history" for item in packages)

    manager.activate_enabled_plugins()
    resolved = sensor_registry.resolve_domain_sensor("timeline", "chrome_history")
    assert resolved is not None
    _, _, sensor, spec = resolved

    result = await sensor.collect_items(
        SensorSyncContext(
            source_type="chrome_history",
            manual=True,
            last_cursor=None,
            last_success_at=None,
            limit=50,
            runtime_paths=Runtimepaths(tmp_path / "runtime"),
            plugin_settings=config.plugins.packages["chrome-history"].settings,
        )
    )

    assert spec.display_name == "Chrome History"
    assert any(field.key == "sensors.chrome_history.profile" for field in spec.fields)
    assert len(result.items) == 3
    assert result.next_cursor == "103"

    incremental = await sensor.collect_items(
        SensorSyncContext(
            source_type="chrome_history",
            manual=False,
            last_cursor="101",
            last_success_at=result.watermark_ts,
            limit=50,
            runtime_paths=Runtimepaths(tmp_path / "runtime-incremental"),
            plugin_settings=config.plugins.packages["chrome-history"].settings,
        )
    )
    assert [item["visit_id"] for item in incremental.items] == ["102", "103"]

    event = await sensor.build_timeline_event(result.items[1])
    assert event.event_id == "chrome_history:102"
    assert "chrome_history" in event.tags
    assert "github.com" in event.tags
    assert event.provenance["browser"] == "chrome"
    assert event.provenance["visit_id"] == "102"

    root_relations = await sensor.extract_candidates(result.items[0])
    content_relations = await sensor.extract_candidates(result.items[1])
    noise_relations = await sensor.extract_candidates(result.items[2])

    assert [candidate["predicate"] for candidate in root_relations["relation_candidates"]] == ["VISITED"]
    assert [candidate["predicate"] for candidate in content_relations["relation_candidates"]] == ["VISITED", "VIEWED"]
    assert [candidate["predicate"] for candidate in noise_relations["relation_candidates"]] == ["VISITED"]
    assert all(candidate["object_id"] == "site:github.com" for candidate in content_relations["relation_candidates"])
