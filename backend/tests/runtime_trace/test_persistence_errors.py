"""Public receipt operations expose domain failures after native cleanup."""

import sqlite3
import pytest

from magi.core.persistence_errors import PersistenceUnavailableError
from magi.notifications.store import NotificationStore
from magi.runtime_trace import RuntimeTraceStore


@pytest.mark.parametrize("operation", ["claim", "read", "resolve", "finish"])
async def test_receipt_operations_translate_missing_schema(tmp_path, operation):
    store = RuntimeTraceStore(db_path=str(tmp_path / "empty.db"))
    with pytest.raises(PersistenceUnavailableError) as failure:
        if operation == "claim":
            await store.claim_plugin_rpc(client_id="device", epoch="epoch", operation_id="operation",
                fingerprint="fingerprint", issued_at_ms=1, connection_id=None)
        elif operation == "read":
            await store.read_plugin_rpc("device", "epoch", "operation")
        elif operation == "resolve":
            await store.resolve_plugin_rpc(client_id="device", epoch="epoch",
                operation_id="operation", issued_at_ms=1)
        else:
            await store.finish_plugin_rpc(client_id="device", epoch="epoch",
                operation_id="operation", http_status=200, result={}, connection_id=None)
    assert isinstance(failure.value.__cause__, sqlite3.Error)
    assert not store.rpc_active
    with sqlite3.connect(store.db_path, timeout=0) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.rollback()


def test_notification_ack_translates_real_driver_failure(tmp_path):
    store = NotificationStore(tmp_path / "empty.db")
    with pytest.raises(PersistenceUnavailableError) as failure:
        store.mark_read([1])
    assert isinstance(failure.value.__cause__, sqlite3.Error)
