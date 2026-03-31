"""Tests for the PhotoLibraryPlugin registration and settings."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# photo-library has a hyphen, so we must load via importlib
_plugin_dir = Path(__file__).resolve().parents[3] / "plugins" / "photo-library"

def _load_module(name: str):
    path = _plugin_dir / f"{name}.py"
    spec = importlib.util.spec_from_file_location(
        f"photo_library_{name}", path,
        submodule_search_locations=[str(_plugin_dir)],
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod

_plugin_mod = _load_module("plugin")
PhotoLibraryPlugin = _plugin_mod.PhotoLibraryPlugin
DEFAULT_SETTINGS = _plugin_mod.DEFAULT_SETTINGS


class TestPhotoLibraryPluginRegistration:
    def test_registers_photo_library_source_type(self) -> None:
        plg = PhotoLibraryPlugin()
        sensors = plg.get_sensors()
        source_types = [spec.metadata["source_type"] for _, _, spec in sensors]
        assert source_types == ["photo_library"]

    def test_does_not_register_other_sources(self) -> None:
        plg = PhotoLibraryPlugin()
        sensors = plg.get_sensors()
        source_types = [spec.metadata["source_type"] for _, _, spec in sensors]
        assert "chat" not in source_types
        assert "manual_journal" not in source_types

    def test_sensor_spec_has_fields(self) -> None:
        plg = PhotoLibraryPlugin()
        _, _, spec = plg.get_sensors()[0]
        assert len(spec.fields) > 0
        field_keys = [f.key for f in spec.fields]
        assert any("enabled" in k for k in field_keys)
        assert any("source_path" in k for k in field_keys)
        assert any("sync_mode" in k for k in field_keys)

    def test_default_settings(self) -> None:
        assert DEFAULT_SETTINGS["enabled"] is False
        assert DEFAULT_SETTINGS["max_items_per_sync"] == 200
        assert DEFAULT_SETTINGS["sync_mode"] == "manual"

    def test_sensor_instance_picks_up_settings(self) -> None:
        plg = PhotoLibraryPlugin()
        plg.settings = {
            "sensors": {
                "photo_library": {
                    "source_path": "/tmp/test_photos",
                    "max_items_per_sync": 50,
                    "default_retention_mode": "analyze_only",
                }
            }
        }
        _, sensor, _ = plg.get_sensors()[0]
        assert sensor.source_path == "/tmp/test_photos"
        assert sensor.max_items_per_sync == 50
        assert sensor.retention_mode == "analyze_only"


class TestBuildTemporalSummaryFeatures:
    def test_returns_none_for_wrong_source_type(self) -> None:
        plg = PhotoLibraryPlugin()
        result = plg.build_temporal_summary_features(
            source_type="browser_history",
            events=[],
            summary_category="daily",
            period_start=0, period_end=0,
        )
        assert result is None

    def test_returns_none_for_empty_events(self) -> None:
        plg = PhotoLibraryPlugin()
        result = plg.build_temporal_summary_features(
            source_type="photo_library",
            events=[],
            summary_category="daily",
            period_start=0, period_end=0,
        )
        assert result is None

    def test_extracts_camera_distribution(self) -> None:
        plg = PhotoLibraryPlugin()
        events = [
            {
                "metadata_json": {
                    "timeline": {
                        "provenance": {
                            "camera": "Canon EOS R5",
                            "filename": "img1.jpg",
                        }
                    }
                },
                "timestamp": 1710000000.0,
            },
            {
                "metadata_json": {
                    "timeline": {
                        "provenance": {
                            "camera": "Canon EOS R5",
                            "filename": "img2.jpg",
                        }
                    }
                },
                "timestamp": 1710000100.0,
            },
            {
                "metadata_json": {
                    "timeline": {
                        "provenance": {
                            "camera": "iPhone 15 Pro",
                            "latitude": 35.6,
                            "filename": "img3.heic",
                        }
                    }
                },
                "timestamp": 1710000200.0,
            },
        ]
        result = plg.build_temporal_summary_features(
            source_type="photo_library",
            events=events,
            summary_category="daily",
            period_start=1710000000.0,
            period_end=1710086400.0,
        )
        assert result is not None
        assert result["event_count"] == 3
        assert result["gps_count"] == 1
        cameras = result["cameras"]
        assert cameras[0]["camera"] == "Canon EOS R5"
        assert cameras[0]["count"] == 2
        assert "jpg" in result["format_distribution"]
