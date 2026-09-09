"""Verify implicit host paths remain isolated during the test suite."""

from magi_plugin_sdk.runtime_paths import get_magi_home

from magi.config.loader import get_config_file
from magi.utils.runtime import RuntimePaths, get_runtime_paths


def test_implicit_host_paths_are_scoped_to_the_current_test(tmp_path):
    assert get_magi_home() == tmp_path / "runtime-home"
    assert get_runtime_paths().base_dir == tmp_path / "runtime-home"
    assert RuntimePaths().base_dir == tmp_path / "runtime-home"
    assert get_config_file().is_relative_to(tmp_path)
