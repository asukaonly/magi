"""Package-carried wheels preserve offline installation and hash admission."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

from magi.plugins.dependency_installation import (
    UnsafeDependencyLockError,
    _build_dependency_install_command,
    _validated_package_wheels,
)
from magi.plugins.package_identity import (
    compute_installed_package_sha256,
    compute_installed_source_sha256,
)


def make_wheel(directory: Path) -> Path:
    directory.mkdir()
    path = directory / "magi_wheel_probe-1.0.0-py3-none-any.whl"
    files = {
        "magi_wheel_probe.py": b"VALUE = 'verified-package-wheel'\n",
        "magi_wheel_probe-1.0.0.dist-info/METADATA": b"Metadata-Version: 2.1\nName: magi-wheel-probe\nVersion: 1.0.0\n",
        "magi_wheel_probe-1.0.0.dist-info/WHEEL": b"Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    record = io.StringIO()
    writer = csv.writer(record)
    for name, content in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
        writer.writerow([name, f"sha256={digest}", len(content)])
    record_path = "magi_wheel_probe-1.0.0.dist-info/RECORD"
    writer.writerow([record_path, "", ""])
    files[record_path] = record.getvalue().encode()
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return path


@pytest.mark.parametrize("tampered", [False, True])
def test_package_wheel_installs_offline_only_with_matching_hash(tmp_path, tampered):
    wheel = make_wheel(tmp_path / "wheels")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    if tampered:
        wheel.write_bytes(wheel.read_bytes() + b"tampered")
    lock = tmp_path / "requirements.lock"
    lock.write_text(f"magi-wheel-probe==1.0.0 --hash=sha256:{digest}\n")
    deps = tmp_path / ".deps"
    command = _build_dependency_install_command(lock, deps, quiet=False)
    assert command[command.index("--find-links") + 1] == str((tmp_path / "wheels").resolve())
    assert "--only-binary=:all:" in command and "--require-hashes" in command
    result = subprocess.run([*command, "--no-index"], capture_output=True, text=True, timeout=60)
    if tampered:
        assert result.returncode != 0
        assert "hash" in (result.stdout + result.stderr).lower()
        assert not (deps / "magi_wheel_probe.py").exists()
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        subprocess.run(
            [
                sys.executable,
                "-I",
                "-S",
                "-c",
                f"import sys; sys.path.insert(0, {str(deps)!r}); "
                "import magi_wheel_probe; assert magi_wheel_probe.VALUE == 'verified-package-wheel'",
            ],
            check=True,
            timeout=30,
        )


def symlink(target: Path, link: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError:
        if os.name == "nt":
            pytest.skip("Creating symlinks requires Windows symlink privileges")
        raise


@pytest.mark.parametrize(
    "kind", ["directory_link", "file_link", "broken_link", "subdirectory", "sdist", "fifo"]
)
def test_rejects_nonregular_or_external_wheel_sources(tmp_path, kind):
    package = tmp_path / "package"
    package.mkdir()
    wheels = package / "wheels"
    outside = tmp_path / "outside"
    outside.mkdir()
    if kind == "directory_link":
        symlink(outside, wheels, directory=True)
    else:
        wheels.mkdir()
        if kind in {"file_link", "broken_link"}:
            target = outside / "probe.whl"
            if kind == "file_link":
                target.touch()
            symlink(target, wheels / "probe.whl")
        elif kind == "subdirectory":
            (wheels / "nested.whl").mkdir()
        elif kind == "sdist":
            (wheels / "source.tar.gz").touch()
        elif kind == "fifo":
            if not hasattr(os, "mkfifo"):
                pytest.skip("Named FIFOs require POSIX")
            os.mkfifo(wheels / "probe.whl")
    with pytest.raises(UnsafeDependencyLockError, match="wheels"):
        _validated_package_wheels(package)


def test_no_package_wheels_does_not_add_search_paths(tmp_path):
    lock = tmp_path / "requirements.lock"
    lock.write_text(f"demo==1.0.0 --hash=sha256:{'a' * 64}\n")
    assert "--find-links" not in _build_dependency_install_command(
        lock, tmp_path / ".deps", quiet=True
    )


def test_vendored_wheel_is_covered_by_source_identity_and_install_seal(tmp_path):
    wheel = make_wheel(tmp_path / "wheels")
    source = compute_installed_source_sha256(tmp_path)
    sealed = compute_installed_package_sha256(tmp_path)
    wheel.write_bytes(wheel.read_bytes() + b"changed-package-artifact")
    assert compute_installed_source_sha256(tmp_path) != source
    assert compute_installed_package_sha256(tmp_path) != sealed

    source = compute_installed_source_sha256(tmp_path)
    sealed = compute_installed_package_sha256(tmp_path)
    dependencies = tmp_path / ".deps"
    dependencies.mkdir()
    (dependencies / "installed.py").write_text("VALUE = 1\n")
    assert compute_installed_source_sha256(tmp_path) == source
    assert compute_installed_package_sha256(tmp_path) != sealed
