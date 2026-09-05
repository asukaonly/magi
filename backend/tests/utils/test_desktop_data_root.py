"""Verify root selection before the packaged worker imports its services."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


def test_fresh_process_keeps_all_default_storage_in_selected_root(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    candidate = tmp_path / "candidate"
    script = '''
import json, os
from pathlib import Path
from magi.utils.runtime import RuntimePaths, get_default_chat_workspace_path
from magi.config.loader import ConfigLoader, get_config_dir
from magi.api.avatar_paths import user_avatar_dir
from magi.plugins.package_files import user_plugins_root
from magi.tools.code_agent._user_paths import code_agent_settings_path
from magi_plugin_sdk.subprocess import DEFAULT_REGISTRY_PATH
from magi.chat.store import ChatStore
from magi.runtime_trace.store import RuntimeTraceStore
paths = RuntimePaths()
loader = ConfigLoader()
config = loader.load()
values = [paths.base_dir, get_config_dir(), user_avatar_dir(), user_plugins_root(),
          code_agent_settings_path(), DEFAULT_REGISTRY_PATH, get_default_chat_workspace_path(),
          config.agent.memory.db_path, config.agent.memory.archive_path, config.agent.personality.path,
          ChatStore().db_path, RuntimeTraceStore().db_path]
assert str(user_plugins_root()) in config.plugins.scan_paths
print('ROOT_PATHS=' + json.dumps([str(value) for value in values]))
'''
    environment = {
        **os.environ,
        "MAGI_HOME": str(candidate),
        "PYTHONPATH": os.pathsep.join([str(root / "src"), str(root.parent / "sdk" / "src")]),
    }
    result = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, env=environment,
                            capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    values = json.loads(next(line.removeprefix("ROOT_PATHS=") for line in result.stdout.splitlines()
                             if line.startswith("ROOT_PATHS=")))
    assert all(Path(value).is_relative_to(candidate) for value in values), values
    assert (candidate / "config" / "agent.yaml").is_file()
