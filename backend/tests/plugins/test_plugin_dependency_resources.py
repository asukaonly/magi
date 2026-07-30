from pathlib import Path
import subprocess
import sys
import time

from pydantic import ValidationError
import pytest

from magi.plugins import dependency_installation as dependency_installation_module
from magi.plugins.contracts import (
    PluginManifest,
    PluginRegistryEntry,
    PluginRegistryIndex,
)
from magi.plugins.dependency_installation import (
    DependencyInstallResourceLimitError,
    PluginDependencyWorkflowBudget,
    _DependencyInstallPlan,
    _run_dependency_install_plan,
    _run_dependency_install_with_progress,
)
from magi.plugins.install_service import PluginInstallService
from magi.plugins.registry_client import PluginRegistrySnapshot
from magi.plugins.registry_provenance import registry_install_fingerprint


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
        "from pathlib import Path\n" f"Path({str(sitecustomize_marker)!r}).write_text('loaded')\n",
        encoding="utf-8",
    )
    shadow_pip = tmp_path / "pip"
    shadow_pip.mkdir()
    (shadow_pip / "__init__.py").write_text("", encoding="utf-8")
    (shadow_pip / "__main__.py").write_text(
        "from pathlib import Path\n" f"Path({str(shadow_pip_marker)!r}).write_text('loaded')\n",
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


def test_dependency_workflow_enforces_cumulative_byte_budget(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        dependency_installation_module,
        "MAX_PLUGIN_DEPENDENCY_WORKFLOW_BYTES",
        5,
    )
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "payload.bin").write_bytes(b"abc")
    (second / "payload.bin").write_bytes(b"def")
    budget = PluginDependencyWorkflowBudget()

    budget.consume((first,))

    with pytest.raises(
        DependencyInstallResourceLimitError,
        match="cumulative byte limit",
    ):
        budget.consume((second,))


@pytest.mark.asyncio
async def test_registry_sources_share_cumulative_workflow_budget_and_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        dependency_installation_module,
        "MAX_PLUGIN_DEPENDENCY_WORKFLOW_BYTES",
        5,
    )
    library = PluginRegistryEntry(
        plugin_id="shared-library",
        name="Shared Library",
        version="1.0.0",
        kind="library",
        path="shared/source",
    )
    target = PluginRegistryEntry(
        plugin_id="demo-plugin",
        name="Demo Plugin",
        version="1.0.0",
        path="shared/source",
        depends_on=["shared-library"],
    )
    index = PluginRegistryIndex(
        plugins=[target, library],
        repo_url="https://github.com/example/plugins.git",
    )
    snapshot = PluginRegistrySnapshot(
        index=index,
        registry_url="https://example.test/registry.json",
        repo_url=index.repo_url,
        install_fingerprint=registry_install_fingerprint(
            index,
            registry_url="https://example.test/registry.json",
            repo_url=index.repo_url,
        ),
        official_source=False,
    )

    class _Registry:
        def __init__(self) -> None:
            self.extracted_dirs: list[Path] = []

        async def fetch_snapshot(
            self,
            *,
            force: bool = False,
            deadline_monotonic: float | None = None,
        ) -> PluginRegistrySnapshot:
            return snapshot

        async def clone_plugin(
            self,
            entry: PluginRegistryEntry,
            *,
            snapshot: PluginRegistrySnapshot,
            dest_dir: Path | None = None,
            deadline_monotonic: float | None = None,
        ) -> Path:
            assert dest_dir is not None
            plugin_dir = dest_dir / entry.plugin_id
            plugin_dir.mkdir()
            (plugin_dir / "payload.bin").write_bytes(b"abc")
            self.extracted_dirs.append(plugin_dir)
            return plugin_dir

    class _Manager:
        def __init__(self) -> None:
            self.install_calls: list[str] = []

        def installed_plugin_ids(self) -> set[str]:
            return set()

        def install_plugin_from_directory(
            self,
            plugin_dir: Path,
            **_kwargs,
        ) -> None:
            self.install_calls.append(plugin_dir.name)

    registry = _Registry()
    manager = _Manager()
    service = PluginInstallService(
        registry_client=registry,
        plugin_manager=manager,
    )
    monkeypatch.setattr(
        "magi.plugins.install_service._validate_registry_package_directory",
        lambda _plugin_dir, entry: PluginManifest(
            id=entry.plugin_id,
            name=entry.name,
            version=entry.version,
            kind=entry.kind,
            depends_on=list(entry.depends_on),
        ),
    )

    with pytest.raises(
        DependencyInstallResourceLimitError,
        match="cumulative byte limit",
    ):
        await service.install_from_registry(
            target.plugin_id,
            expected_fingerprint=snapshot.install_fingerprint,
        )

    assert len(registry.extracted_dirs) == 2
    assert all(not plugin_dir.exists() for plugin_dir in registry.extracted_dirs)
    assert manager.install_calls == []


def test_dependency_workflow_rejects_expired_deadline() -> None:
    budget = PluginDependencyWorkflowBudget(
        deadline_monotonic=time.monotonic() - 1,
    )

    with pytest.raises(RuntimeError, match="workflow time limit"):
        budget.ensure_time_remaining()


def test_dependency_install_process_receives_workflow_deadline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path, [sys.executable, "-c", "pass"])
    deadline = time.monotonic() + 60
    budget = PluginDependencyWorkflowBudget(deadline_monotonic=deadline)
    captured: dict[str, object] = {}

    def fake_run(
        cmd: list[str],
        **kwargs,
    ) -> subprocess.CompletedProcess[str]:
        captured.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(
        dependency_installation_module,
        "_run_dependency_install_process",
        fake_run,
    )

    _run_dependency_install_plan(plan, None, workflow_budget=budget)

    assert captured["deadline_monotonic"] == deadline


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
