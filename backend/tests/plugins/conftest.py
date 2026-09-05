"""Plugin test helpers — ensure plugin source directories are importable."""
from __future__ import annotations

import sys

import pytest
from pathlib import Path

_PLUGINS_ROOT = Path(__file__).resolve().parents[3] / "plugins"

if _PLUGINS_ROOT.is_dir():
    for _plugin_dir in _PLUGINS_ROOT.iterdir():
        if _plugin_dir.is_dir():
            _dir_str = str(_plugin_dir)
            if _dir_str not in sys.path:
                sys.path.insert(0, _dir_str)


@pytest.fixture(autouse=True)
def isolated_plugin_runtime_config(monkeypatch, tmp_path_factory):
    """Run the fresh-schema contract without reading developer account state."""
    from magi.config import loader
    from magi.utils.runtime import RuntimePaths

    runtime_root = tmp_path_factory.mktemp("plugin-runtime")
    monkeypatch.setattr(loader, "get_magi_home", lambda: runtime_root / "magi-user")
    monkeypatch.setattr(loader, "_loader", loader.ConfigLoader())
    paths = RuntimePaths(runtime_root / "runtime")
    monkeypatch.setattr("magi.plugins.connections.get_runtime_paths", lambda: paths)
