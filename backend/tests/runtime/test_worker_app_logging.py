from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from magi.bootstrap import worker_app


def test_configure_worker_logging_uses_runtime_log_file(monkeypatch, tmp_path: Path) -> None:
    runtime_paths = SimpleNamespace(logs_dir=tmp_path)
    configure_logging = Mock()

    monkeypatch.setattr(worker_app, "get_runtime_paths", lambda: runtime_paths)
    monkeypatch.setattr(worker_app, "configure_logging", configure_logging)

    log_path = worker_app.configure_worker_logging()

    assert log_path == tmp_path / "magi.log"
    configure_logging.assert_called_once_with(
        level="INFO",
        log_file=str(tmp_path / "magi.log"),
        json_logs=False,
    )


def test_ipc_auth_token_is_removed_before_runtime_startup(monkeypatch) -> None:
    monkeypatch.setenv("MAGI_IPC_SOCKET", "/tmp/magi-ipc.sock")
    monkeypatch.setenv(worker_app.IPC_AUTH_TOKEN_ENV, "  internal-secret  ")

    assert worker_app._consume_ipc_auth_token() == "internal-secret"
    assert worker_app.IPC_AUTH_TOKEN_ENV not in os.environ


def test_ipc_worker_fails_closed_without_auth_token(monkeypatch) -> None:
    monkeypatch.setenv("MAGI_IPC_SOCKET", "/tmp/magi-ipc.sock")
    monkeypatch.delenv(worker_app.IPC_AUTH_TOKEN_ENV, raising=False)

    with pytest.raises(RuntimeError, match="MAGI_IPC_AUTH_TOKEN is required"):
        worker_app._consume_ipc_auth_token()
