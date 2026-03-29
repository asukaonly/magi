"""Plugin test helpers — ensure plugin source directories are importable."""
from __future__ import annotations

import sys
from pathlib import Path

_PLUGINS_ROOT = Path(__file__).resolve().parents[3] / "plugins"

if _PLUGINS_ROOT.is_dir():
    for _plugin_dir in _PLUGINS_ROOT.iterdir():
        if _plugin_dir.is_dir():
            _dir_str = str(_plugin_dir)
            if _dir_str not in sys.path:
                sys.path.insert(0, _dir_str)
