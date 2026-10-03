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


def test_run_server_rejects_unsupported_standalone_http_roles() -> None:
    """Verify run_server raises for roles that need the Rust gateway."""
    run_server = _load_run_server_module()
    source = Path(run_server.__file__).read_text(encoding="utf-8")

    assert "uvicorn" not in source
    assert "backend_app" not in source
    assert "ipc_worker" in source


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
    from magi.utils import inference_runtime

    launcher = _load_run_server_module()

    def fail_validation():
        raise RuntimeError("Required inference runtime sherpa_onnx could not be loaded")

    monkeypatch.setattr(sys, "argv", [str(launcher.__file__), "--check-inference-runtime"])
    monkeypatch.setattr(inference_runtime, "validate_inference_runtime", fail_validation)
    assert launcher.run() == 1
    assert "Required inference runtime sherpa_onnx" in capsys.readouterr().err
