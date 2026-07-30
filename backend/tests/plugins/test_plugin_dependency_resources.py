from pathlib import Path
import subprocess
import sys
import time

from pydantic import ValidationError
import pytest

from magi.plugins import dependency_installation as dependency_installation_module
from magi.plugins.contracts import PluginManifest
from magi.plugins.dependency_installation import (
    DependencyInstallResourceLimitError,
    _DependencyInstallPlan,
    _run_dependency_install_plan,
    _run_dependency_install_with_progress,
)


def _plan(staging_dir: Path, command: list[str]) -> _DependencyInstallPlan:
    deps_dir = staging_dir / ".deps"
    deps_dir.mkdir()
    return _DependencyInstallPlan(
        cmd=command,
        label="Installing test dependencies",
        deps_dir=deps_dir,
        staging_dir=staging_dir,
    )


def test_manifest_rejects_too_many_direct_dependencies() -> None:
    with pytest.raises(ValidationError, match="too_long"):
        PluginManifest(
            id="dependency-heavy",
            name="Dependency Heavy",
            version="1.0.0",
            dependencies=[f"package-{index}" for index in range(129)],
        )


def test_dependency_install_uses_and_cleans_staging_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    plan = _plan(tmp_path, [sys.executable, "-c", "pass"])

    def fake_run(
        cmd: list[str],
        *,
        progress_reporter,
        monitored_roots,
        env,
        cwd,
    ) -> subprocess.CompletedProcess[str]:
        captured.update(
            {
                "cmd": cmd,
                "progress_reporter": progress_reporter,
                "monitored_roots": monitored_roots,
                "env": env,
                "cwd": cwd,
            }
        )
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(
        dependency_installation_module,
        "_run_dependency_install_process",
        fake_run,
    )

    _run_dependency_install_plan(plan, None)

    install_env = captured["env"]
    assert isinstance(install_env, dict)
    workspace = Path(install_env["TMPDIR"])
    assert workspace.parent == tmp_path
    assert install_env["TEMP"] == str(workspace)
    assert install_env["TMP"] == str(workspace)
    assert install_env["PIP_NO_CACHE_DIR"] == "1"
    assert install_env["PYTHONNOUSERSITE"] == "1"
    assert "PYTHONPATH" not in install_env
    assert "PYTHONHOME" not in install_env
    assert captured["cwd"] == workspace
    assert workspace in captured["monitored_roots"]
    assert plan.deps_dir in captured["monitored_roots"]
    assert not workspace.exists()


def test_dependency_process_cannot_import_modules_from_staging(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sitecustomize_marker = tmp_path / "sitecustomize-loaded"
    shadow_pip_marker = tmp_path / "shadow-pip-loaded"
    (tmp_path / "sitecustomize.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(sitecustomize_marker)!r}).write_text('loaded')\n",
        encoding="utf-8",
    )
    shadow_pip = tmp_path / "pip"
    shadow_pip.mkdir()
    (shadow_pip / "__init__.py").write_text("", encoding="utf-8")
    (shadow_pip / "__main__.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(shadow_pip_marker)!r}).write_text('loaded')\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    plan = _plan(
        tmp_path,
        [sys.executable, "-m", "pip", "--version"],
    )

    _run_dependency_install_plan(plan, None)

    assert not sitecustomize_marker.exists()
    assert not shadow_pip_marker.exists()


def test_dependency_install_stops_when_byte_budget_is_exceeded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        dependency_installation_module,
        "MAX_PLUGIN_DEPENDENCY_INSTALL_BYTES",
        128,
    )
    monkeypatch.setattr(
        dependency_installation_module,
        "DEPENDENCY_RESOURCE_CHECK_INTERVAL_SECONDS",
        0.01,
    )
    plan = _plan(
        tmp_path,
        [
            sys.executable,
            "-c",
            (
                "from pathlib import Path; import sys, time; "
                "Path(sys.argv[1], 'payload.bin').write_bytes(b'x' * 1024); "
                "time.sleep(10)"
            ),
            str(tmp_path / ".deps"),
        ],
    )

    started = time.monotonic()
    with pytest.raises(DependencyInstallResourceLimitError, match="byte limit"):
        _run_dependency_install_plan(plan, None)

    assert time.monotonic() - started < 3


def test_dependency_install_stops_when_entry_budget_is_exceeded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        dependency_installation_module,
        "MAX_PLUGIN_DEPENDENCY_INSTALL_ENTRIES",
        2,
    )
    monkeypatch.setattr(
        dependency_installation_module,
        "DEPENDENCY_RESOURCE_CHECK_INTERVAL_SECONDS",
        0.01,
    )
    plan = _plan(
        tmp_path,
        [
            sys.executable,
            "-c",
            (
                "from pathlib import Path; import sys, time; "
                "root = Path(sys.argv[1]); "
                "[(root / f'item-{index}').write_text('x') for index in range(4)]; "
                "time.sleep(10)"
            ),
            str(tmp_path / ".deps"),
        ],
    )

    started = time.monotonic()
    with pytest.raises(DependencyInstallResourceLimitError, match="entry limit"):
        _run_dependency_install_plan(plan, None)

    assert time.monotonic() - started < 3


def test_dependency_install_rechecks_final_deps_size(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        dependency_installation_module,
        "MAX_PLUGIN_DEPENDENCY_INSTALL_BYTES",
        64,
    )
    plan = _plan(tmp_path, [sys.executable, "-c", "pass"])

    def fake_run(cmd: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        (plan.deps_dir / "payload.bin").write_bytes(b"x" * 65)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(
        dependency_installation_module,
        "_run_dependency_install_process",
        fake_run,
    )

    with pytest.raises(DependencyInstallResourceLimitError, match="byte limit"):
        _run_dependency_install_plan(plan, None)


def test_dependency_output_keeps_bounded_truncated_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        dependency_installation_module,
        "MAX_PLUGIN_DEPENDENCY_OUTPUT_LINE_CHARS",
        32,
    )
    monkeypatch.setattr(
        dependency_installation_module,
        "MAX_PLUGIN_DEPENDENCY_OUTPUT_BYTES",
        80,
    )
    progress_messages: list[str] = []

    result = _run_dependency_install_with_progress(
        [
            sys.executable,
            "-c",
            (
                "print('x' * 200); "
                "[print(f'line-{index:02d}-' + 'y' * 16) for index in range(20)]"
            ),
        ],
        lambda _stage, message, _progress: progress_messages.append(message),
    )

    assert result.returncode == 0
    assert len(result.stdout.encode("utf-8")) <= 80
    assert result.stdout.splitlines()[-1].startswith("line-19-")
    assert progress_messages[0].startswith("[truncated] ")
    assert all("\n" not in message for message in progress_messages)
    assert all(len(message) <= 32 for message in progress_messages)
