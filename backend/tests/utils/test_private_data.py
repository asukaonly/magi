from __future__ import annotations

import os
from pathlib import Path
import stat
import sys

import pytest

from magi.utils.private_data import PrivateDataProtectionError, protect_private_data_tree
from magi.utils.runtime import RuntimePaths


pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission assertions")


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


def test_protect_private_data_tree_repairs_legacy_modes(tmp_path: Path) -> None:
    root = tmp_path / ".magi"
    config_dir = root / "config"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "llm.yaml"
    executable = root / "plugins" / "helper"
    executable.parent.mkdir()
    config_file.write_text("api_key: secret", encoding="utf-8")
    executable.write_bytes(b"binary")
    root.chmod(0o755)
    config_dir.chmod(0o775)
    config_file.chmod(0o644)
    executable.chmod(0o755)

    result = protect_private_data_tree(root)

    assert _mode(root) == 0o700
    assert _mode(config_dir) == 0o700
    assert _mode(config_file) == 0o600
    assert _mode(executable) == 0o700
    assert result.protected_directories == 3
    assert result.protected_files == 2


def test_protect_private_data_tree_rejects_symlink_without_touching_target(
    tmp_path: Path,
) -> None:
    root = tmp_path / ".magi"
    root.mkdir()
    external = tmp_path / "external.txt"
    external.write_text("outside", encoding="utf-8")
    external.chmod(0o644)
    (root / "linked-secret").symlink_to(external)

    with pytest.raises(PrivateDataProtectionError, match="must not be a link"):
        protect_private_data_tree(root)

    assert _mode(external) == 0o644


def test_protect_private_data_tree_rejects_hard_link_without_touching_target(
    tmp_path: Path,
) -> None:
    root = tmp_path / ".magi"
    root.mkdir()
    external = tmp_path / "external.txt"
    external.write_text("outside", encoding="utf-8")
    external.chmod(0o644)
    os.link(external, root / "linked-secret")

    with pytest.raises(PrivateDataProtectionError, match="must not have external hard links"):
        protect_private_data_tree(root)

    assert _mode(external) == 0o644


def test_protect_private_data_tree_rejects_symlinked_root(tmp_path: Path) -> None:
    external = tmp_path / "external"
    external.mkdir()
    root = tmp_path / ".magi"
    root.symlink_to(external, target_is_directory=True)

    with pytest.raises(PrivateDataProtectionError, match="root must be a real directory"):
        protect_private_data_tree(root)


def test_runtime_paths_create_private_known_directories(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path / "home" / ".magi")

    for directory in (
        paths.base_dir,
        paths.data_dir,
        paths.runtime_dir,
        paths.logs_dir,
        paths.config_dir,
        paths.mcp_config_dir,
        paths.chat_resources_dir,
    ):
        assert directory.is_dir()
        assert _mode(directory) == 0o700
