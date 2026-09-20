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


@pytest.fixture(autouse=True)
def report_test_worker_startup_failure(monkeypatch):
    """Expose bounded stderr from synthetic workers when platform startup fails."""
    from magi.plugins.process_runtime import ProcessPluginProxy

    launch = ProcessPluginProxy._launch

    def observed_launch(self, *args, **kwargs):
        try:
            return launch(self, *args, **kwargs)
        except BaseException:
            self._terminate("Test worker startup failed")
            print("Synthetic worker startup stderr:", bytes(self._stderr).decode("utf-8", "replace"))
            raise

    monkeypatch.setattr(ProcessPluginProxy, "_launch", observed_launch)
