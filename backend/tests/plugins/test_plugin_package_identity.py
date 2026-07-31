from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import subprocess
from types import SimpleNamespace
import unicodedata

import pytest

from magi.plugins import package_identity as package_identity_module
from magi.plugins.package_identity import (
    compute_installed_package_sha256,
    compute_installed_source_sha256,
    InvalidPluginPackageDigestError,
    InvalidPluginPackageRootError,
    PluginPackageDigestMismatchError,
    PluginPackageContentChangedError,
    UnsafePluginPackageEntryError,
    compute_package_sha256,
    purge_plugin_bytecode_caches,
    verify_package_sha256,
)


def _write(root: Path, relative_path: str, content: bytes = b"content") -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_package_identity_changes_with_file_content(tmp_path: Path) -> None:
    plugin_root = tmp_path / "plugin"
    source = _write(plugin_root, "plugin.toml", b"version = 1\n")
    original = compute_package_sha256(plugin_root)

    source.write_bytes(b"version = 2\n")

    assert compute_package_sha256(plugin_root) != original


def test_package_identity_changes_with_relative_path(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    _write(first_root, "module.py", b"same")
    _write(second_root, "renamed.py", b"same")

    assert compute_package_sha256(first_root) != compute_package_sha256(second_root)


def test_package_identity_is_cross_platform_stable_for_executable_permission(
    tmp_path: Path,
) -> None:
    plugin_root = tmp_path / "plugin"
    executable = _write(plugin_root, "run.sh", b"#!/bin/sh\n")
    executable.chmod(0o644)
    without_execute = compute_package_sha256(plugin_root)

    executable.chmod(0o755)

    assert executable.stat().st_mode & stat.S_IXUSR
    assert compute_package_sha256(plugin_root) == without_execute


def test_package_identity_is_stable_across_creation_order_and_mtime(
    tmp_path: Path,
) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    _write(first_root, "z-last.txt", b"z")
    _write(first_root, "nested/first.txt", b"a")
    _write(second_root, "nested/first.txt", b"a")
    _write(second_root, "z-last.txt", b"z")

    os.utime(first_root / "z-last.txt", (100, 100))
    os.utime(second_root / "z-last.txt", (200, 200))

    assert compute_package_sha256(first_root) == compute_package_sha256(second_root)


def test_package_identity_matches_fixed_cross_repository_vector(tmp_path: Path) -> None:
    plugin_root = tmp_path / "plugin"
    manifest = _write(plugin_root, "plugin.toml", b'id = "demo"\n')
    executable = _write(plugin_root, "scripts/run.py", b'print("ok")\n')
    manifest.chmod(0o644)
    executable.chmod(0o755)

    assert (
        compute_package_sha256(plugin_root)
        == "5b341aaf7c8be8205e00a5713bc8c41ad0ce67d757142e30790e94b6defae163"
    )


@pytest.mark.parametrize(
    "relative_path",
    [
        ".deps/package.py",
        ".DEPS/package.py",
        "__pycache__/module.pyc",
        "__PYCACHE__/module.pyc",
        "nested/__pycache__/module.pyc",
        "module.pyc",
        "module.pyo",
        "MODULE.PYC",
    ],
)
def test_source_package_rejects_runtime_artifacts(
    tmp_path: Path,
    relative_path: str,
) -> None:
    plugin_root = tmp_path / "plugin"
    _write(plugin_root, "plugin.toml")
    _write(plugin_root, relative_path)

    with pytest.raises(UnsafePluginPackageEntryError, match="runtime artifact"):
        compute_package_sha256(plugin_root)


def test_installed_source_view_skips_only_dependency_directory(
    tmp_path: Path,
) -> None:
    plugin_root = tmp_path / "plugin"
    _write(plugin_root, "plugin.toml", b"manifest")
    baseline = compute_package_sha256(plugin_root)

    _write(plugin_root, ".deps/library.py", b"dependency")

    assert compute_installed_source_sha256(plugin_root) == baseline

    _write(plugin_root, "module.pyc", b"bytecode")
    _write(plugin_root, "module.pyo", b"optimized bytecode")

    assert compute_installed_source_sha256(plugin_root) != baseline

    (plugin_root / "module.pyc").unlink()
    (plugin_root / "module.pyo").unlink()
    _write(plugin_root, "nested/.deps/library.py", b"source content")

    assert compute_installed_source_sha256(plugin_root) != baseline


def test_installed_package_seal_includes_dependency_contents(tmp_path: Path) -> None:
    plugin_root = tmp_path / "plugin"
    _write(plugin_root, "plugin.toml", b"manifest")
    _write(plugin_root, ".deps/library.py", b"dependency")
    original = compute_installed_package_sha256(plugin_root)

    _write(plugin_root, ".deps/library.py", b"changed dependency")

    assert compute_installed_package_sha256(plugin_root) != original


def test_installed_package_requires_bytecode_caches_to_be_purged(
    tmp_path: Path,
) -> None:
    plugin_root = tmp_path / "plugin"
    _write(plugin_root, "plugin.toml", b"manifest")
    _write(plugin_root, "__pycache__/plugin.cpython-313.pyc", b"cache")
    _write(plugin_root, "nested/__PYCACHE__/plugin.cpython-313.pyc", b"cache")
    _write(
        plugin_root,
        ".deps/library/__PyCache__/module.cpython-313.pyc",
        b"dependency cache",
    )

    with pytest.raises(UnsafePluginPackageEntryError, match="was not cleared"):
        compute_installed_package_sha256(plugin_root)

    purge_plugin_bytecode_caches(plugin_root)

    assert not list(plugin_root.rglob("__pycache__"))
    assert not list(plugin_root.rglob("__PYCACHE__"))
    assert not list(plugin_root.rglob("__PyCache__"))
    assert compute_installed_package_sha256(plugin_root)


def test_installed_package_rejects_link_in_place_of_skipped_directory(
    tmp_path: Path,
) -> None:
    plugin_root = tmp_path / "plugin"
    outside = tmp_path / "outside"
    plugin_root.mkdir()
    outside.mkdir()
    try:
        (plugin_root / ".deps").symlink_to(outside, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"Symbolic links are unavailable: {exc}")

    with pytest.raises(UnsafePluginPackageEntryError, match="symbolic links"):
        compute_installed_package_sha256(plugin_root)


@pytest.mark.parametrize("link_is_directory", [False, True])
def test_package_identity_rejects_symbolic_links(
    tmp_path: Path,
    link_is_directory: bool,
) -> None:
    plugin_root = tmp_path / "plugin"
    target = tmp_path / "target"
    plugin_root.mkdir()
    if link_is_directory:
        target.mkdir()
    else:
        target.write_bytes(b"target")
    try:
        (plugin_root / "link").symlink_to(target, target_is_directory=link_is_directory)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"Symbolic links are unavailable: {exc}")

    with pytest.raises(UnsafePluginPackageEntryError, match="symbolic links"):
        compute_package_sha256(plugin_root)


def test_package_identity_rejects_hard_links(tmp_path: Path) -> None:
    plugin_root = tmp_path / "plugin"
    source = _write(plugin_root, "source.py")
    try:
        os.link(source, plugin_root / "alias.py")
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"Hard links are unavailable: {exc}")

    with pytest.raises(UnsafePluginPackageEntryError, match="hard-linked"):
        compute_package_sha256(plugin_root)


def test_package_identity_rejects_special_files(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO files are unavailable")
    plugin_root = tmp_path / "plugin"
    plugin_root.mkdir()
    fifo = plugin_root / "events"
    try:
        os.mkfifo(fifo)
    except OSError as exc:
        pytest.skip(f"FIFO files are unavailable: {exc}")

    with pytest.raises(UnsafePluginPackageEntryError, match="special files"):
        compute_package_sha256(plugin_root)


@pytest.mark.parametrize(
    "relative_path",
    [
        "CON.txt",
        "nested/AUX",
        "trailing.",
        "trailing ",
        "stream:name",
        "backslash\\name",
        'quote"name',
        "less<name",
        "greater>name",
        "pipe|name",
        "question?name",
        "star*name",
    ],
)
def test_package_identity_rejects_non_portable_paths(
    tmp_path: Path,
    relative_path: str,
) -> None:
    plugin_root = tmp_path / "plugin"
    try:
        _write(plugin_root, relative_path)
    except OSError as exc:
        pytest.skip(f"Filesystem cannot create the non-portable path: {exc}")

    with pytest.raises(UnsafePluginPackageEntryError):
        compute_package_sha256(plugin_root)


def test_package_identity_rejects_case_conflicting_paths(tmp_path: Path) -> None:
    plugin_root = tmp_path / "plugin"
    _write(plugin_root, "Source/first.py")
    _write(plugin_root, "source/second.py")
    if not {"Source", "source"}.issubset(os.listdir(plugin_root)):
        pytest.skip("Filesystem merges case-conflicting directory names")

    with pytest.raises(UnsafePluginPackageEntryError, match="portable spellings"):
        compute_package_sha256(plugin_root)


def test_package_identity_rejects_nfc_conflicting_paths(tmp_path: Path) -> None:
    plugin_root = tmp_path / "plugin"
    nfc_name = unicodedata.normalize("NFC", "cafe\u0301")
    nfd_name = unicodedata.normalize("NFD", "cafe\u0301")
    _write(plugin_root, f"{nfc_name}/first.py")
    _write(plugin_root, f"{nfd_name}/second.py")
    if not {nfc_name, nfd_name}.issubset(os.listdir(plugin_root)):
        pytest.skip("Filesystem merges Unicode-normalization-conflicting names")

    with pytest.raises(UnsafePluginPackageEntryError, match="portable spellings"):
        compute_package_sha256(plugin_root)


def test_package_identity_rejects_invalid_roots(tmp_path: Path) -> None:
    ordinary_file = tmp_path / "plugin.toml"
    ordinary_file.write_bytes(b"manifest")

    with pytest.raises(InvalidPluginPackageRootError):
        compute_package_sha256(tmp_path / "missing")
    with pytest.raises(InvalidPluginPackageRootError):
        compute_package_sha256(ordinary_file)

    link = tmp_path / "plugin-link"
    try:
        link.symlink_to(tmp_path, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"Symbolic links are unavailable: {exc}")
    with pytest.raises(InvalidPluginPackageRootError, match="symbolic link"):
        compute_package_sha256(link)


def test_link_helper_rejects_windows_reparse_metadata() -> None:
    reparse_directory = SimpleNamespace(
        st_mode=stat.S_IFDIR,
        st_file_attributes=0x400,
    )
    ordinary_directory = SimpleNamespace(
        st_mode=stat.S_IFDIR,
        st_file_attributes=0,
    )

    assert package_identity_module._is_link_or_reparse_point(reparse_directory) is True
    assert package_identity_module._is_link_or_reparse_point(ordinary_directory) is False


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior")
def test_windows_junctions_are_never_traversed_or_cleaned(tmp_path: Path) -> None:
    def create_junction(link: Path, target: Path) -> None:
        result = subprocess.run(
            [
                "cmd.exe",
                "/d",
                "/c",
                "mklink",
                "/J",
                str(link),
                str(target),
            ],
            capture_output=True,
            check=False,
            text=True,
        )
        if result.returncode != 0:
            pytest.skip(f"Cannot create a Windows junction: {result.stderr.strip()}")

    root_target = tmp_path / "root-target"
    root_target.mkdir()
    _write(root_target, "plugin.toml")
    root_junction = tmp_path / "root-junction"
    create_junction(root_junction, root_target)
    try:
        with pytest.raises(InvalidPluginPackageRootError, match="reparse point"):
            compute_package_sha256(root_junction)
    finally:
        root_junction.rmdir()

    plugin_root = tmp_path / "plugin"
    plugin_root.mkdir()
    _write(plugin_root, "plugin.toml")
    outside = tmp_path / "outside"
    sentinel = _write(outside, "__pycache__/sentinel.pyc", b"outside")
    nested_junction = plugin_root / "nested-junction"
    create_junction(nested_junction, outside)
    try:
        with pytest.raises(UnsafePluginPackageEntryError, match="reparse points"):
            compute_package_sha256(plugin_root)
        with pytest.raises(UnsafePluginPackageEntryError, match="reparse points"):
            purge_plugin_bytecode_caches(plugin_root)
        assert sentinel.read_bytes() == b"outside"
    finally:
        nested_junction.rmdir()


def test_verify_package_sha256_uses_canonical_digest(tmp_path: Path) -> None:
    plugin_root = tmp_path / "plugin"
    _write(plugin_root, "plugin.toml", b"manifest")
    expected = compute_package_sha256(plugin_root)

    assert verify_package_sha256(plugin_root, expected) is None
    with pytest.raises(PluginPackageDigestMismatchError, match="digest mismatch"):
        verify_package_sha256(plugin_root, "0" * 64)
    with pytest.raises(InvalidPluginPackageDigestError, match="lowercase"):
        verify_package_sha256(plugin_root, expected.upper())


def test_package_identity_is_independent_of_root_location(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    _write(source, "nested/plugin.py", b"source")
    shutil.copytree(source, destination)

    assert compute_package_sha256(source) == compute_package_sha256(destination)


def test_package_identity_rejects_entry_added_during_hashing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plugin_root = tmp_path / "plugin"
    _write(plugin_root, "plugin.toml", b"manifest")
    original_collect = package_identity_module._collect_package_files
    collect_count = 0

    def collect_with_change(root: Path, *, scan_profile: str):
        nonlocal collect_count
        collect_count += 1
        if collect_count == 2:
            _write(plugin_root, "late.py", b"changed")
        return original_collect(root, scan_profile=scan_profile)

    monkeypatch.setattr(
        package_identity_module,
        "_collect_package_files",
        collect_with_change,
    )

    with pytest.raises(PluginPackageContentChangedError, match="entries changed"):
        compute_package_sha256(plugin_root)
