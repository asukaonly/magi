from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_plugin_class():
    module_path = Path(__file__).resolve().parents[3] / "plugins" / "core-timeline" / "plugin.py"
    spec = importlib.util.spec_from_file_location("core_timeline_plugin_under_test", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.CoreTimelinePlugin


def test_core_timeline_plugin_does_not_register_chat_source() -> None:
    plugin = _load_plugin_class()()

    sensors = plugin.get_sensors()
    source_types = [spec.metadata["source_type"] for _, _, spec in sensors]

    assert source_types == ["manual_journal", "browser_history", "photo_library"]
    assert "chat" not in source_types
