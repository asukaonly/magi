from pathlib import Path

import pytest

from magi.plugins import dependency_installation as dependency_installation_module
from magi.plugins.installation import (
    ALLOW_UNLOCKED_DEPS_ENV,
    UnlockedDependencyError,
    _build_dependency_install_command,
    _build_loose_dependency_install_command,
    _developer_mode_allows_unlocked,
    _resolve_lock_or_policy,
)
from magi.plugins.dependency_installation import UnsafeDependencyLockError


def test_build_command_uses_require_hashes_and_lockfile(tmp_path: Path) -> None:
    deps_dir = tmp_path / ".deps"
    lock = tmp_path / "requirements.lock"
    lock.write_text(f"segno==1.6.1 --hash=sha256:{'a' * 64}\n")

    cmd = _build_dependency_install_command(lock, deps_dir, quiet=True)

    assert "--require-hashes" in cmd
    assert "--only-binary=:all:" in cmd
    assert "--no-cache-dir" in cmd
    assert "-r" in cmd
    assert str(lock) in cmd
    assert "--target" in cmd
    assert str(deps_dir) in cmd
    # user mirror config must keep working: never hard-code an index
    assert "--index-url" not in cmd
    assert "-i" not in cmd


@pytest.mark.parametrize(
    "dependencies,locked,env_value,expected",
    [
        ([], False, None, "none"),
        ([], True, "true", "none"),
        (["segno>=1.6.1"], True, None, "lock"),
        (["segno>=1.6.1"], True, "true", "lock"),
        *[
            (["segno>=1.6.1"], False, value, "loose")
            for value in ["1", "true", "True", "TRUE", "yes", "on"]
        ],
        *[
            (["segno>=1.6.1"], False, value, "error")
            for value in [None, "", "0", "false", "no", "off", "nope"]
        ],
    ],
)
def test_lock_policy_prefers_integrity_and_only_allows_explicit_developer_override(
    tmp_path, monkeypatch, dependencies, locked, env_value, expected
):
    if env_value is None:
        monkeypatch.delenv(ALLOW_UNLOCKED_DEPS_ENV, raising=False)
    else:
        monkeypatch.setenv(ALLOW_UNLOCKED_DEPS_ENV, env_value)
    lock = tmp_path / "requirements.lock"
    if locked:
        lock.write_text(f"segno==1.6.1 --hash=sha256:{'a' * 64}\n")
    allowed = _developer_mode_allows_unlocked()
    if expected == "error":
        with pytest.raises(UnlockedDependencyError):
            _resolve_lock_or_policy(dependencies, tmp_path, allow_unlocked=allowed)
    else:
        result = _resolve_lock_or_policy(dependencies, tmp_path, allow_unlocked=allowed)
        assert result == {"none": None, "lock": lock, "loose": dependencies}[expected]


def test_locked_command_accepts_multiline_exact_pins_with_markers(
    tmp_path: Path,
) -> None:
    lock = tmp_path / "requirements.lock"
    lock.write_text(
        "demo-package==1.2.3 ; sys_platform == 'darwin' \\\n"
        f"    --hash=sha256:{'a' * 64} \\\n"
        f"    --hash=sha256:{'b' * 64}\n"
        "    # via demo\n"
    )

    cmd = _build_dependency_install_command(lock, tmp_path / ".deps", quiet=False)

    assert "--only-binary=:all:" in cmd


def test_locked_command_requires_manifest_dependencies_to_be_covered(
    tmp_path: Path,
) -> None:
    lock = tmp_path / "requirements.lock"
    lock.write_text(
        f"urllib3==2.5.0 --hash=sha256:{'a' * 64}\n",
        encoding="utf-8",
    )

    with pytest.raises(UnsafeDependencyLockError, match="requests"):
        _build_dependency_install_command(
            lock,
            tmp_path / ".deps",
            quiet=False,
            declared_dependencies=["Requests>=2"],
        )


def test_locked_command_allows_extra_transitive_dependencies(tmp_path: Path) -> None:
    lock = tmp_path / "requirements.lock"
    lock.write_text(
        f"requests==2.32.5 --hash=sha256:{'a' * 64}\n"
        f"urllib3==2.5.0 --hash=sha256:{'b' * 64}\n",
        encoding="utf-8",
    )

    cmd = _build_dependency_install_command(
        lock,
        tmp_path / ".deps",
        quiet=False,
        declared_dependencies=["Requests>=2"],
    )

    assert "--require-hashes" in cmd


def test_locked_command_rejects_too_many_entries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        dependency_installation_module,
        "MAX_PLUGIN_DEPENDENCY_LOCK_ENTRIES",
        1,
    )
    lock = tmp_path / "requirements.lock"
    lock.write_text(
        f"requests==2.32.5 --hash=sha256:{'a' * 64}\n"
        f"urllib3==2.5.0 --hash=sha256:{'b' * 64}\n",
        encoding="utf-8",
    )

    with pytest.raises(UnsafeDependencyLockError, match="too many"):
        _build_dependency_install_command(lock, tmp_path / ".deps", quiet=False)


@pytest.mark.parametrize(
    "content",
    [
        f"demo-package>=1.2 --hash=sha256:{'a' * 64}\n",
        f"demo-package==1.* --hash=sha256:{'a' * 64}\n",
        f"demo-package @ file:///tmp/demo.tar.gz --hash=sha256:{'a' * 64}\n",
        f"demo-package @ https://example.com/demo.whl --hash=sha256:{'a' * 64}\n",
        "--no-binary :all:\n",
        "demo-package==1.2.3\n",
        "demo-package==1.2.3 --hash=sha256:abc\n",
    ],
)
def test_locked_command_rejects_source_and_uncontrolled_requirements(
    tmp_path: Path,
    content: str,
) -> None:
    lock = tmp_path / "requirements.lock"
    lock.write_text(content)

    with pytest.raises(UnsafeDependencyLockError):
        _build_dependency_install_command(lock, tmp_path / ".deps", quiet=False)


@pytest.mark.parametrize("dependencies", [[], ["segno>=1.6.1"]])
@pytest.mark.parametrize("quiet", [False, True])
def test_loose_command_keeps_python_pip_prefix_and_option_order(
    tmp_path, monkeypatch, dependencies, quiet
):
    monkeypatch.setattr(
        dependency_installation_module,
        "_resolve_dependency_python_executable",
        lambda: "/test-runtime/python",
    )
    deps_dir = tmp_path / ".deps"
    command = _build_loose_dependency_install_command(dependencies, deps_dir, quiet=quiet)
    expected = [
        "/test-runtime/python",
        "-m",
        "pip",
        "install",
        "--target",
        str(deps_dir.resolve()),
        "--no-user",
        "--disable-pip-version-check",
        "--no-cache-dir",
    ]
    if quiet and dependencies:
        expected.append("--quiet")
    assert command == expected + dependencies
