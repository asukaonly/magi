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


@pytest.mark.asyncio
async def test_restore_worker_recovers_before_transport_without_starting_agents(monkeypatch) -> None:
    from unittest.mock import AsyncMock
    from magi.bootstrap import maintenance_worker
    from magi.memory.portability import recovery
    from magi.transport import http_app

    operation_id = '77777777-7777-4777-8777-777777777777'
    monkeypatch.setenv('MAGI_MEMORY_RESTORE_OPERATION_ID', operation_id)
    monkeypatch.setattr(maintenance_worker, '_restore_operation_id', None)
    monkeypatch.setattr(worker_app, 'wire_container', Mock())
    start = AsyncMock()
    monkeypatch.setattr(worker_app, 'initialize_agent_runtime', start)
    recovered = Mock(return_value='none')
    monkeypatch.setattr(recovery, 'recover_pending_memory_restore', recovered)
    paths = object()
    monkeypatch.setattr(worker_app, 'get_runtime_paths', lambda: paths)
    transport = object()
    monkeypatch.setattr(http_app, 'create_transport_app', lambda **kwargs: transport)

    assert await worker_app._initialize_worker_transport_app() is transport
    recovered.assert_called_once_with(paths)
    start.assert_not_awaited()
    assert 'MAGI_MEMORY_RESTORE_OPERATION_ID' not in os.environ
    assert maintenance_worker.owns_restore_operation(operation_id)
    assert not maintenance_worker.owns_restore_operation('different')


@pytest.mark.asyncio
async def test_management_transport_does_not_wait_for_optional_activation(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock
    from magi.bootstrap import maintenance_worker
    from magi.transport import http_app

    base = AsyncMock()
    entered = asyncio.Event()
    release = asyncio.Event()
    async def activate():
        entered.set()
        await release.wait()
    monkeypatch.setattr(maintenance_worker, 'consume_restore_operation', lambda: None)
    monkeypatch.setattr(maintenance_worker, 'is_restore_worker', lambda: False)
    monkeypatch.setattr(worker_app, 'wire_container', Mock())
    monkeypatch.setattr(worker_app, 'initialize_base_runtime', base)
    monkeypatch.setattr(worker_app, 'initialize_agent_runtime', activate)
    transport = object()
    monkeypatch.setattr(http_app, 'create_transport_app', lambda **kwargs: transport)
    assert await worker_app._initialize_worker_transport_app() is transport
    base.assert_awaited_once()
    assert not entered.is_set()
    task = worker_app._start_runtime_activation()
    await entered.wait()
    assert not task.done()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
