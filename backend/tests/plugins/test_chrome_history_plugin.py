from __future__ import annotations

import shutil
import os
import copy
import sys
import sqlite3
import time
from pathlib import Path

import pytest

from magi.config.models import AppConfig, PluginSettings
from magi.plugins import package_files as package_files_module
from magi.plugins.manager import PluginManager
from magi.plugins.package_identity import (
    compute_installed_package_sha256,
    compute_installed_source_sha256,
)
from magi.plugins.registry_client import DEFAULT_REGISTRY_URL, DEFAULT_REPO_URL
from magi.plugins.sensors import SensorRegistry
from magi.timeline import SensorSyncContext
from magi_plugin_sdk.sensors import ScopedSensorRuntimePaths
from runtime_fixtures import instantiate_fixture_plugin
from magi.tools.registry import ToolRegistry
from magi.utils.runtime import RuntimePaths

_CHROME_EPOCH_OFFSET_S = 11644473600


def _chrome_us(seconds_ago: float) -> int:
    """Chrome-epoch microseconds for a moment ``seconds_ago`` before now.

    The sensor's default ``initial_sync_policy=lookback_days`` (7 days)
    filters out old visits, so fixtures must seed RECENT timestamps.
    """
    return int((time.time() - seconds_ago + _CHROME_EPOCH_OFFSET_S) * 1_000_000)


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
        connection.executescript("""
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
            """)
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
            (101, 1, _chrome_us(3600), 0, 536870912),
        )
        connection.execute(
            "INSERT INTO visits (id, url, visit_time, from_visit, transition) VALUES (?, ?, ?, ?, ?)",
            (102, 2, _chrome_us(3600 - 600), 101, 536870912),
        )
        connection.execute(
            "INSERT INTO visits (id, url, visit_time, from_visit, transition) VALUES (?, ?, ?, ?, ?)",
            (103, 3, _chrome_us(3600 - 1200), 102, 536870912),
        )
        connection.commit()
    finally:
        connection.close()
    return root


def _create_bursty_history_db(root: Path) -> Path:
    profile_dir = root / "Default"
    profile_dir.mkdir(parents=True, exist_ok=True)
    db_path = profile_dir / "History"
    connection = sqlite3.connect(db_path)
    try:
        connection.executescript("""
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
            """)
        rows = [
            (
                1,
                "https://mermaid.live/edit#pako:first",
                "Online FlowChart & Diagrams Editor - Mermaid Live Editor",
                8,
                201,
                _chrome_us(3600),
            ),
            (
                2,
                "https://mermaid.live/edit#pako:second",
                "Online FlowChart & Diagrams Editor - Mermaid Live Editor",
                8,
                202,
                _chrome_us(3600 - 15),
            ),
            (
                3,
                "https://mermaid.live/edit#pako:third",
                "Online FlowChart & Diagrams Editor - Mermaid Live Editor",
                8,
                203,
                _chrome_us(3600 - 30),
            ),
            (
                4,
                "http://www.last.fm/music/Radiohead",
                "Radiohead | Last.fm",
                5,
                204,
                _chrome_us(3600 - 600),
            ),
            (
                5,
                "https://last.fm/music/Radiohead/",
                "Radiohead | Last.fm",
                5,
                205,
                _chrome_us(3600 - 620),
            ),
        ]
        for url_id, url, title, visit_count, visit_id, visit_time in rows:
            connection.execute(
                "INSERT INTO urls (id, url, title, visit_count) VALUES (?, ?, ?, ?)",
                (url_id, url, title, visit_count),
            )
            connection.execute(
                "INSERT INTO visits (id, url, visit_time, from_visit, transition) VALUES (?, ?, ?, ?, ?)",
                (visit_id, url_id, visit_time, max(0, visit_id - 1), 536870912),
            )
        connection.commit()
    finally:
        connection.close()
    return root


def _create_search_bursty_history_db(root: Path) -> Path:
    profile_dir = root / "Default"
    profile_dir.mkdir(parents=True, exist_ok=True)
    db_path = profile_dir / "History"
    connection = sqlite3.connect(db_path)
    try:
        connection.executescript("""
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
            """)
        rows = [
            (
                1,
                "https://www.google.com/search?q=%E9%87%8E%E7%8A%AC+%E8%AF%B4%E6%B3%95&sca_esv=foo",
                "野犬 说法 - Google Search",
                4,
                301,
                _chrome_us(3600),
            ),
            (
                2,
                "https://google.com/search?q=%E9%87%8E%E7%8A%AC+%E8%AF%B4%E6%B3%95&sxsrf=bar&ved=1",
                "野犬 说法 - Google Search",
                4,
                302,
                _chrome_us(3600 - 2),
            ),
            (
                3,
                "https://google.com/search?newwindow=1&udm=7&q=%E9%87%8E%E7%8A%AC+%E8%AF%B4%E6%B3%95",
                "野犬 说法 - Google Search",
                4,
                303,
                _chrome_us(3600 - 4),
            ),
            (
                4,
                "https://google.com/search?q=%E9%87%8E%E7%8A%AC+%E8%AF%B4%E6%B3%95&mstk=baz",
                "野犬 说法 - Google Search",
                4,
                304,
                _chrome_us(3600 - 58),
            ),
        ]
        for url_id, url, title, visit_count, visit_id, visit_time in rows:
            connection.execute(
                "INSERT INTO urls (id, url, title, visit_count) VALUES (?, ?, ?, ?)",
                (url_id, url, title, visit_count),
            )
            connection.execute(
                "INSERT INTO visits (id, url, visit_time, from_visit, transition) VALUES (?, ?, ?, ?, ?)",
                (visit_id, url_id, visit_time, max(0, visit_id - 1), 536870912),
            )
        connection.commit()
    finally:
        connection.close()
    return root


def _plugin_root() -> Path:
    repository_root = Path(os.environ.get(
        "MAGI_PLUGINS_REPO", Path(__file__).resolve().parents[4] / "magi-plugins",
    ))
    return repository_root / "plugins"



if not (
    _plugin_root() / "chrome-history"
).exists():  # pragma: no cover - plugin repo absent (e.g. CI)
    pytest.skip(
        "chrome-history plugin not available (magi-plugins is a separate repo); "
        "plugin-backed tests run only where the plugin is checked out",
        allow_module_level=True,
    )


def _build_manager(
    monkeypatch: pytest.MonkeyPatch,
    config: AppConfig,
    tmp_path: Path,
    *, connection_settings: dict,
) -> tuple[PluginManager, SensorRegistry]:
    sensor_registry = SensorRegistry()
    source_plugin_root = _plugin_root()
    plugin_root = tmp_path / "installed-plugins"
    for plugin_id in ("chrome-history", "browser_history_core"):
        shutil.copytree(
            source_plugin_root / plugin_id,
            plugin_root / plugin_id,
            ignore=shutil.ignore_patterns(
                "__pycache__",
                ".pytest_cache",
                ".deps",
                "*.pyc",
                "*.pyo",
                ".DS_Store",
            ),
        )
    chrome_dir = plugin_root / "chrome-history"
    library_dir = plugin_root / "browser_history_core"
    manifest_path = chrome_dir / "plugin.toml"
    library_manifest_path = library_dir / "plugin.toml"
    chrome_package_sha256 = compute_installed_source_sha256(chrome_dir)
    library_package_sha256 = compute_installed_source_sha256(library_dir)
    configured = config.plugins.packages.get("chrome-history", PluginSettings())
    if isinstance(configured, dict):
        configured = PluginSettings.model_validate(configured)
    config.plugins.packages["chrome-history"] = configured.model_copy(
        update={
            "source": "external",
            "trusted": True,
            "manifest_path": str(manifest_path),
            "install_origin": "registry",
            "registry_source": DEFAULT_REGISTRY_URL,
            "registry_repo_url": DEFAULT_REPO_URL,
            "package_sha256": chrome_package_sha256,
            "installed_package_sha256": compute_installed_package_sha256(chrome_dir),
            "dependency_package_sha256": {
                "browser_history_core": library_package_sha256,
            },
        }
    )
    config.plugins.packages["browser_history_core"] = PluginSettings(
        trusted=True,
        source="external",
        manifest_path=str(library_manifest_path),
        install_origin="registry",
        registry_source=DEFAULT_REGISTRY_URL,
        registry_repo_url=DEFAULT_REPO_URL,
        package_sha256=library_package_sha256,
        installed_package_sha256=compute_installed_package_sha256(library_dir),
    )

    def save_config_updates(updates: dict[str, object]) -> bool:
        _apply_updates(config, updates)
        return True

    monkeypatch.setattr(package_files_module, "user_plugins_root", lambda: plugin_root)
    monkeypatch.setattr("magi.plugins.manager.get_config", lambda: config)
    monkeypatch.setattr("magi.plugins.manager.save_config", save_config_updates)
    monkeypatch.setattr("magi.plugins.installation.get_config", lambda: config)
    monkeypatch.setattr("magi.plugins.installation.save_config", save_config_updates)
    paths = RuntimePaths(tmp_path / "runtime")
    monkeypatch.setattr("magi.plugins.connections.get_runtime_paths", lambda: paths)

    def instantiate(manifest, connection, context):
        plugin = instantiate_fixture_plugin(manifest, connection, context)
        source_path = connection_settings.get("sensors", {}).get("chrome_history", {}).get("source_path")
        if source_path:
            monkeypatch.setattr(sys.modules[type(plugin).__module__], "_default_chrome_root", lambda: source_path)
        return plugin

    manager = PluginManager(
        instance_factory=instantiate,
        tool_registry=ToolRegistry(),
        sensor_registry=sensor_registry,
        search_paths=[plugin_root],
        request_sensor_schedule_refresh=lambda: None,
    )
    return manager, sensor_registry


def _activate(manager: PluginManager, connection_settings: dict):
    settings = copy.deepcopy(connection_settings)
    source_settings = settings.get("sensors", {}).get("chrome_history", {})
    source_settings.pop("source_path", None)
    source_settings.pop("fetch_page_content", None)
    connection = manager.create_connection(
        "chrome-history", display_name="Test Chrome profile", settings=settings, enabled=True,
    )
    manager.activate_enabled_plugins()
    return connection


def test_chrome_history_requires_connection_and_defaults_source_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    connection_settings = {}
    config = AppConfig()
    manager, sensor_registry = _build_manager(monkeypatch, config, tmp_path, connection_settings=connection_settings)

    packages = manager.scan(persist_discovery=True)
    chrome_package = next(item for item in packages if item.manifest.plugin_id == "chrome-history")

    assert chrome_package.enabled is False
    assert manager.connection_store.list("chrome-history") == []
    # The sibling-repo source is copied into a temporary managed install root.
    assert chrome_package.manifest.source == "external"
    assert chrome_package.manifest.official is True

    connection = _activate(manager, connection_settings)
    resolved = sensor_registry.resolve_domain_sensor("timeline", "chrome_history", connection_id=connection.connection_id)
    assert resolved is not None
    _, _, _, spec = resolved
    assert spec.metadata["default_settings"]["enabled"] is False
    assert "edge_whitelist" not in spec.metadata["default_settings"]
    activation_flow = spec.metadata["activation_flow"]
    assert activation_flow["enabled_key"] == "sensors.chrome_history.enabled"
    assert activation_flow["configured_key"] == "sensors.chrome_history.initial_sync_configured"
    assert activation_flow["fields"][0]["key"] == "sensors.chrome_history.initial_sync_policy"
    assert all(field.key != "sensors.chrome_history.source_path" for field in spec.fields)
    assert all(field.key != "sensors.chrome_history.edge_whitelist" for field in spec.fields)
    sync_mode_field = next(
        field for field in spec.fields if field.key == "sensors.chrome_history.sync_mode"
    )
    assert [option.value for option in sync_mode_field.options] == ["manual", "interval"]
    sync_interval_field = next(
        field
        for field in spec.fields
        if field.key == "sensors.chrome_history.sync_interval_minutes"
    )
    assert sync_interval_field.depends_on_key == "sensors.chrome_history.sync_mode"
    assert sync_interval_field.depends_on_values == ["interval"]


def test_chrome_history_sensor_exposes_plugin_translations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    connection_settings = {}
    config = AppConfig()
    manager, sensor_registry = _build_manager(monkeypatch, config, tmp_path, connection_settings=connection_settings)

    manager.scan(persist_discovery=False)
    connection = _activate(manager, connection_settings)
    resolved = sensor_registry.resolve_domain_sensor("timeline", "chrome_history", connection_id=connection.connection_id)

    assert resolved is not None
    _, _, sensor, _ = resolved
    assert sensor.t("summary.multiple_visits", title="GitHub", count=3) == "GitHub (3 visits)"


@pytest.mark.asyncio
async def test_chrome_history_sensor_collects_events_and_relations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    chrome_root = _create_history_db(tmp_path / "chrome")
    connection_settings = {
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
                }
            }
        }
    config = AppConfig()
    config.plugins.packages["chrome-history"] = PluginSettings(
        trusted=True,
        source="builtin",
    )
    manager, sensor_registry = _build_manager(monkeypatch, config, tmp_path, connection_settings=connection_settings)

    packages = manager.scan(persist_discovery=False)
    assert any(item.manifest.plugin_id == "chrome-history" for item in packages)

    connection = _activate(manager, connection_settings)
    resolved = sensor_registry.resolve_domain_sensor("timeline", "chrome_history", connection_id=connection.connection_id)
    assert resolved is not None
    _, _, sensor, spec = resolved

    result = await sensor.collect_items(
        SensorSyncContext(
            connection_id=connection.connection_id,
            source_type="chrome_history",
            manual=True,
            last_cursor=None,
            last_success_at=None,
            limit=50,
            runtime_paths=ScopedSensorRuntimePaths(connection.connection_id, connection.plugin_id, sensor.context.state_dir),
            plugin_settings=connection.settings,
        )
    )

    assert spec.display_name == "Chrome History"
    assert any(field.key == "sensors.chrome_history.profile" for field in spec.fields)
    assert len(result.changes) == 3
    assert result.next_cursor == "103"

    incremental = await sensor.collect_items(
        SensorSyncContext(
            connection_id=connection.connection_id,
            source_type="chrome_history",
            manual=False,
            last_cursor="101",
            last_success_at=result.watermark_ts,
            limit=50,
            runtime_paths=ScopedSensorRuntimePaths(connection.connection_id, connection.plugin_id, sensor.context.state_dir),
            plugin_settings=connection.settings,
        )
    )
    assert [item["visit_id"] for item in (change.payload for change in incremental.changes)] == ["102", "103"]

    output = await sensor.build_output(result.changes[1].payload)
    assert output.source_type == "chrome_history"
    assert output.source_item_id == "102"
    assert "chrome_history" in output.tags
    assert "github.com" in output.tags
    assert output.provenance["browser"] == "chrome"
    assert output.provenance["visit_id"] == "102"
    policy = sensor.l2_batch_policy(output)
    assert policy is not None
    # L2 batching is day-keyed now (chrome_history:<profile>:<YYYYMMDD>).
    import re as _re

    assert _re.fullmatch(r"chrome_history:Default:\d{8}", policy.owner)
    assert policy.catch_up_owner == "chrome_history:Default:catchup"
    assert policy.max_events == 20
    assert policy.min_ready_events == 8
    assert policy.max_wait_seconds == 300

    root_metadata = await sensor.extract_metadata(result.changes[0].payload)
    content_metadata = await sensor.extract_metadata(result.changes[1].payload)
    noise_metadata = await sensor.extract_metadata(result.changes[2].payload)

    assert root_metadata.relation_candidates == []
    assert [candidate["predicate"] for candidate in content_metadata.relation_candidates] == [
        "VIEWED"
    ]
    assert noise_metadata.relation_candidates == []
    assert all(
        candidate["object_id"] == "site:github.com"
        for candidate in content_metadata.relation_candidates
    )


@pytest.mark.asyncio
async def test_chrome_history_sensor_merges_burst_visits_and_keeps_cursor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    chrome_root = _create_bursty_history_db(tmp_path / "chrome-bursty")
    connection_settings = {
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
                }
            }
        }
    config = AppConfig()
    config.plugins.packages["chrome-history"] = PluginSettings(
        trusted=True,
        source="builtin",
    )
    manager, sensor_registry = _build_manager(monkeypatch, config, tmp_path, connection_settings=connection_settings)
    manager.scan(persist_discovery=False)
    connection = _activate(manager, connection_settings)
    resolved = sensor_registry.resolve_domain_sensor("timeline", "chrome_history", connection_id=connection.connection_id)
    assert resolved is not None
    _, _, sensor, _ = resolved

    result = await sensor.collect_items(
        SensorSyncContext(
            connection_id=connection.connection_id,
            source_type="chrome_history",
            manual=True,
            last_cursor=None,
            last_success_at=None,
            limit=50,
            runtime_paths=ScopedSensorRuntimePaths(connection.connection_id, connection.plugin_id, sensor.context.state_dir),
            plugin_settings=connection.settings,
        )
    )

    assert len(result.changes) == 2
    assert result.next_cursor == "205"
    assert result.stats["raw_count"] == 5

    mermaid_item = result.changes[0].payload
    lastfm_item = result.changes[1].payload

    assert mermaid_item["source_item_id"] == "201-203"
    assert mermaid_item["merged_visit_count"] == 3
    assert mermaid_item["url"] == "https://mermaid.live/edit"
    assert mermaid_item["canonical_url"] == "https://mermaid.live/edit"

    mermaid_output = await sensor.build_output(mermaid_item)
    assert mermaid_output.source_type == "chrome_history"
    assert mermaid_output.source_item_id == "201-203"
    # SensorOutput carries activity+narration now; the visit summary lives in
    # narration.body ("{title} ({count} visits)").
    assert mermaid_output.narration.body.endswith("(3 visits)")
    assert mermaid_output.provenance["merged_visit_count"] == 3
    assert mermaid_output.provenance["canonical_url"] == "https://mermaid.live/edit"

    mermaid_metadata = await sensor.extract_metadata(mermaid_item)
    assert [candidate["predicate"] for candidate in mermaid_metadata.relation_candidates] == [
        "VIEWED"
    ]
    assert all(
        candidate["object_id"] == "site:mermaid.live"
        for candidate in mermaid_metadata.relation_candidates
    )

    assert lastfm_item["source_item_id"] == "204-205"
    assert lastfm_item["merged_visit_count"] == 2
    assert lastfm_item["url"] == "https://last.fm/music/Radiohead"


@pytest.mark.asyncio
async def test_chrome_history_sensor_merges_search_visits_despite_query_churn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    chrome_root = _create_search_bursty_history_db(tmp_path / "chrome-search-bursty")
    connection_settings = {
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
                }
            }
        }
    config = AppConfig()
    config.plugins.packages["chrome-history"] = PluginSettings(
        trusted=True,
        source="builtin",
    )
    manager, sensor_registry = _build_manager(monkeypatch, config, tmp_path, connection_settings=connection_settings)
    manager.scan(persist_discovery=False)
    connection = _activate(manager, connection_settings)
    resolved = sensor_registry.resolve_domain_sensor("timeline", "chrome_history", connection_id=connection.connection_id)
    assert resolved is not None
    _, _, sensor, _ = resolved

    result = await sensor.collect_items(
        SensorSyncContext(
            connection_id=connection.connection_id,
            source_type="chrome_history",
            manual=True,
            last_cursor=None,
            last_success_at=None,
            limit=50,
            runtime_paths=ScopedSensorRuntimePaths(connection.connection_id, connection.plugin_id, sensor.context.state_dir),
            plugin_settings=connection.settings,
        )
    )

    assert len(result.changes) == 1
    assert result.next_cursor == "304"
    assert result.stats["raw_count"] == 4

    item = result.changes[0].payload
    assert item["source_item_id"] == "301-304"
    assert item["merged_visit_count"] == 4
    assert item["domain"] == "google.com"


@pytest.mark.asyncio
async def test_chrome_history_sensor_from_now_skips_initial_backfill(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    chrome_root = _create_history_db(tmp_path / "chrome-from-now")
    connection_settings = {
            "sensors": {
                "chrome_history": {
                    "enabled": True,
                    "source_path": str(chrome_root),
                    "profile": "Default",
                    "sync_mode": "manual",
                    "sync_interval_minutes": 30,
                    "initial_sync_policy": "from_now",
                    "initial_sync_lookback_days": 3,
                    "initial_sync_configured": True,
                    "max_items_per_sync": 50,
                    "fetch_page_content": False,
                }
            }
        }
    config = AppConfig()
    config.plugins.packages["chrome-history"] = PluginSettings(
        trusted=True,
        source="builtin",
    )
    manager, sensor_registry = _build_manager(monkeypatch, config, tmp_path, connection_settings=connection_settings)
    manager.scan(persist_discovery=False)
    connection = _activate(manager, connection_settings)
    resolved = sensor_registry.resolve_domain_sensor("timeline", "chrome_history", connection_id=connection.connection_id)
    assert resolved is not None
    _, _, sensor, _ = resolved

    result = await sensor.collect_items(
        SensorSyncContext(
            connection_id=connection.connection_id,
            source_type="chrome_history",
            manual=True,
            last_cursor=None,
            last_success_at=None,
            limit=50,
            runtime_paths=ScopedSensorRuntimePaths(connection.connection_id, connection.plugin_id, sensor.context.state_dir),
            plugin_settings=connection.settings,
        )
    )

    assert result.changes == []
    assert result.next_cursor == "103"
    assert result.stats["initial_sync_policy"] == "from_now"


def test_chrome_history_plugin_builds_temporal_summary_features(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    connection_settings = {}
    config = AppConfig()
    config.plugins.packages["chrome-history"] = PluginSettings(
        trusted=True,
        source="builtin",
    )
    manager, _sensor_registry = _build_manager(monkeypatch, config, tmp_path, connection_settings=connection_settings)
    manager.scan(persist_discovery=False)
    connection = _activate(manager, connection_settings)
    plugin = manager.get_connection_plugin(connection.connection_id)

    features = plugin.build_temporal_summary_features(
        source_type="chrome_history",
        events=[
            {
                "event_id": "evt-1",
                "source": "chrome_history",
                "content": "OpenAI docs for tool calling",
                "metadata_json": {
                    "activity_snapshot": {
                        "provenance": {
                            "domain": "openai.com",
                            "canonical_url": "https://openai.com/docs/tool-calling",
                            "merged_visit_count": 2,
                        }
                    }
                },
            },
            {
                "event_id": "evt-2",
                "source": "chrome_history",
                "content": "OpenAI docs pricing page",
                "metadata_json": {
                    "activity_snapshot": {
                        "provenance": {
                            "domain": "openai.com",
                            "canonical_url": "https://openai.com/pricing",
                            "merged_visit_count": 1,
                        }
                    }
                },
            },
            {
                "event_id": "evt-3",
                "source": "chrome_history",
                "content": "GitHub repository issues",
                "metadata_json": {
                    "activity_snapshot": {
                        "provenance": {
                            "domain": "github.com",
                            "canonical_url": "https://github.com/openai/openai-python/issues",
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

    assert features is not None
    assert features["feature_type"] == "chrome_history"
    assert features["event_count"] == 3
    assert features["visit_count"] == 4
    assert features["unique_domain_count"] == 2
    assert features["focus_domain"] == "openai.com"
    assert features["focus_share"] == pytest.approx(2 / 3, rel=1e-3)
    assert features["session_count"] == 1
    assert features["top_domains"] == [
        {"domain": "openai.com", "count": 2},
        {"domain": "github.com", "count": 1},
    ]
    assert features["revisit_domains"] == ["openai.com"]
    assert features["summary_lines"] == [
        "Browsing concentrated heavily on openai.com.",
        "Repeated visits clustered around openai.com.",
        "Browsing stayed within a small set of sites.",
    ]
