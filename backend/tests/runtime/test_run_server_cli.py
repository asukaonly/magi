from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path


def _load_run_server_module():
    module_path = Path(__file__).resolve().parents[2] / "run_server.py"
    spec = importlib.util.spec_from_file_location("run_server_under_test", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load run_server module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_launcher_enters_ipc_worker_only_while_instance_is_owned(monkeypatch, tmp_path):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from magi.bootstrap.process_roles import PROCESS_ROLE_ENV_VAR
    from magi_plugin_sdk import runtime_paths
    from magi.utils import log_redaction, worker_instance

    launcher = _load_run_server_module()
    events = []
    home = tmp_path / "worker-home"

    @contextmanager
    def own_instance(actual_home, parent_pid):
        assert actual_home == home
        assert parent_pid == 1234
        events.append("owned")
        try:
            yield
        finally:
            events.append("released")

    def run_worker():
        assert events == ["owned"]
        assert os.environ[PROCESS_ROLE_ENV_VAR] == "ipc_worker"
        assert "MAGI_SERVER_PARENT_PID" not in os.environ
        events.append("worker")

    monkeypatch.setattr(sys, "argv", [str(launcher.__file__), "--role=ipc_worker"])
    monkeypatch.setenv("MAGI_SERVER_PARENT_PID", "1234")
    monkeypatch.setenv(PROCESS_ROLE_ENV_VAR, "unset")
    monkeypatch.setattr(runtime_paths, "get_magi_home", lambda: home)
    monkeypatch.setattr(worker_instance, "WorkerInstance", own_instance)
    monkeypatch.setattr(log_redaction, "install_redacting_standard_streams", lambda: None)
    monkeypatch.setitem(sys.modules, "magi.bootstrap.worker_app", SimpleNamespace(main=run_worker))
    assert launcher.run() == 0
    assert events == ["owned", "worker", "released"]


def test_run_server_converts_startup_exception_to_nonzero_exit(
    monkeypatch,
    capsys,
) -> None:
    """Verify packaged startup failures are logged instead of escaping."""
    run_server = _load_run_server_module()

    def fail_startup() -> None:
        raise RuntimeError("migration startup failed")

    monkeypatch.setattr(run_server, "main", fail_startup)

    assert run_server.run() == 1
    captured = capsys.readouterr()
    assert "Traceback (most recent call last)" in captured.err
    assert "RuntimeError: migration startup failed" in captured.err


def test_inference_check_exits_without_starting_service_or_creating_user_data(tmp_path):
    home = tmp_path / "unused-home"
    launcher = Path(__file__).resolve().parents[2] / "run_server.py"
    result = subprocess.run(
        [sys.executable, str(launcher), "--check-inference-runtime"],
        env={**os.environ, "MAGI_HOME": str(home)},
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert not home.exists()


def test_inference_check_returns_failure_without_starting_worker(monkeypatch, capsys):
    from magi.utils import inference_runtime, worker_instance
    from unittest.mock import Mock

    owner = Mock(side_effect=AssertionError("Preflight must not acquire a worker instance"))
    monkeypatch.setattr(worker_instance, "WorkerInstance", owner)

    launcher = _load_run_server_module()

    def fail_validation():
        raise RuntimeError("Required inference runtime sherpa_onnx could not be loaded")

    monkeypatch.setattr(sys, "argv", [str(launcher.__file__), "--check-inference-runtime"])
    monkeypatch.setattr(inference_runtime, "validate_inference_runtime", fail_validation)
    assert launcher.run() == 1
    assert "Required inference runtime sherpa_onnx" in capsys.readouterr().err
    owner.assert_not_called()
