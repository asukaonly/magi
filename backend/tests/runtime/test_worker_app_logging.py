from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

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
