"""Regression tests: plugin install must preserve the executable bit on
files inside the plugin's bin/ directory.

Before this fix, marketplace install (registry_client._extract_subdir_from_tarball)
wrote tarball file contents via target_path.write_bytes() and never restored
the tar member's mode. ZIP install called
zipfile.extractall() which also drops Unix permissions.

The result: shipped helper binaries (e.g. screenshot_timeline's Swift helper)
landed as -rw-r--r-- and could never be spawned, so sources that depended on
them silently failed.
"""
from __future__ import annotations

import io
import os
import stat
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

import pytest


def _build_tarball_with_executable(plugin_subdir: str = "plugins/test_plugin") -> bytes:
    """Build an in-memory GitHub-style tarball whose plugin contains an
    executable file under bin/.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        # Mimic GitHub's top-level prefix.
        top_prefix = "owner-repo-abc1234/"

        # Root dir entry (GitHub tarballs include it).
        root_info = tarfile.TarInfo(name=top_prefix)
        root_info.type = tarfile.DIRTYPE
        root_info.mode = 0o755
        tf.addfile(root_info)

        # plugin.toml — regular file
        toml_payload = b'[plugin]\nid = "test_plugin"\nname = "Test"\nversion = "0.1.0"\nentry_module = "x"\nentry_class = "Y"\n'
        toml_info = tarfile.TarInfo(name=f"{top_prefix}{plugin_subdir}/plugin.toml")
        toml_info.size = len(toml_payload)
        toml_info.mode = 0o644
        tf.addfile(toml_info, io.BytesIO(toml_payload))

        # bin/native-helper — executable
        helper_payload = b"#!/bin/sh\necho hi\n"
        helper_info = tarfile.TarInfo(name=f"{top_prefix}{plugin_subdir}/bin/native-helper")
        helper_info.size = len(helper_payload)
        helper_info.mode = 0o755
        tf.addfile(helper_info, io.BytesIO(helper_payload))

    return buf.getvalue()


@pytest.mark.skipif(sys.platform == "win32", reason="Unix mode bits not preserved on Windows")
def test_marketplace_extract_preserves_executable_bit(tmp_path: Path) -> None:
    """registry_client._extract_subdir_from_tarball must preserve the x bit."""
    from magi.plugins.registry_client import _extract_subdir_from_tarball

    tarball = _build_tarball_with_executable()
    _extract_subdir_from_tarball(tarball, subdir="plugins/test_plugin", dest=tmp_path)

    helper = tmp_path / "bin" / "native-helper"
    assert helper.exists()
    mode = helper.stat().st_mode
    assert mode & stat.S_IXUSR, f"helper not executable: mode={oct(mode)}"

    # plugin.toml stays non-executable
    toml = tmp_path / "plugin.toml"
    assert toml.exists()
    toml_mode = toml.stat().st_mode
    assert not (toml_mode & stat.S_IXUSR), f"plugin.toml unexpectedly executable: mode={oct(toml_mode)}"


@pytest.mark.skipif(sys.platform == "win32", reason="Unix mode bits not preserved on Windows")
def test_archive_install_preserves_executable_bit_for_tar(tmp_path: Path) -> None:
    """Tar archive extraction preserves modes."""
    from magi.plugins.package_files import extract_plugin_archive

    # Build a tar.gz where the plugin tree is at root (not nested under owner-repo-x)
    archive = tmp_path / "plugin.tar.gz"
    payload = b"#!/bin/sh\necho hi\n"
    with tarfile.open(archive, "w:gz") as tf:
        info = tarfile.TarInfo(name="plugin.toml")
        info.size = 4
        info.mode = 0o644
        tf.addfile(info, io.BytesIO(b"x=1\n"))

        info = tarfile.TarInfo(name="bin/native-helper")
        info.size = len(payload)
        info.mode = 0o755
        tf.addfile(info, io.BytesIO(payload))

    dest = tmp_path / "extracted"
    dest.mkdir()
    extract_plugin_archive(archive, dest)

    helper = dest / "bin" / "native-helper"
    assert helper.exists()
    assert helper.stat().st_mode & stat.S_IXUSR


@pytest.mark.skipif(sys.platform == "win32", reason="Unix mode bits not preserved on Windows")
def test_archive_install_preserves_executable_bit_for_zip(tmp_path: Path) -> None:
    """Zip archive extraction recovers modes from external_attr."""
    from magi.plugins.package_files import extract_plugin_archive

    archive = tmp_path / "plugin.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("plugin.toml", "x=1\n")
        # zip files store Unix permissions in upper 16 bits of external_attr.
        info = zipfile.ZipInfo(filename="bin/native-helper")
        info.external_attr = (0o755 << 16) | (info.external_attr & 0xFFFF)
        zf.writestr(info, "#!/bin/sh\necho hi\n")

    dest = tmp_path / "extracted"
    dest.mkdir()
    extract_plugin_archive(archive, dest)

    helper = dest / "bin" / "native-helper"
    assert helper.exists()
    assert helper.stat().st_mode & stat.S_IXUSR, (
        f"zip-extracted helper not executable: mode={oct(helper.stat().st_mode)}"
    )
