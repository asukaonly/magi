from __future__ import annotations

import importlib.util
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
