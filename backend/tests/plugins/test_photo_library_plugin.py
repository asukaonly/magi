from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_plugin_class():
    module_path = Path(__file__).resolve().parents[3] / "plugins" / "photo-library" / "plugin.py"
    plugin_dir = str(module_path.parent)
    spec = importlib.util.spec_from_file_location(
        "photo_library_plugin_under_test",
        module_path,
        submodule_search_locations=[plugin_dir],
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.PhotoLibraryPlugin


def test_photo_library_plugin_registers_only_photo_library_source() -> None:
    plugin = _load_plugin_class()()

    sensors = plugin.get_sensors()
    source_types = [spec.metadata["source_type"] for _, _, spec in sensors]

    assert source_types == ["photo_library"]
    assert "chat" not in source_types
    assert "manual_journal" not in source_types
