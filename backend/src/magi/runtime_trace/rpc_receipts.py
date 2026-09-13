"""Durable receipts for explicitly admitted plugin mutations, never a command queue."""

from __future__ import annotations

import json
import time
from typing import Any

import aiosqlite

from ..core.sqlite import sqlite_connection_async


class RpcReceiptPersistenceMixin:
    db_path: str
    rpc_owner: str
    rpc_active: set[tuple[str, str, str]]

    async def claim_plugin_rpc(
        self, *, client_id: str, epoch: str, operation_id: str, fingerprint: str,
        issued_at_ms: int, connection_id: str | None,
    ) -> tuple[bool, dict[str, Any]]:
        """Reserve an attempt before side effects; a duplicate never starts new work."""
        now = int(time.time() * 1000)
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA synchronous=FULL")
            await db.execute("BEGIN IMMEDIATE")
            row = await (await db.execute(
                "SELECT * FROM plugin_rpc_receipts WHERE client_id=? AND data_epoch=? AND operation_id=?",
                (client_id, epoch, operation_id),
            )).fetchone()
            if row is not None:
                if row["fingerprint"] != fingerprint:
                    raise ValueError("Operation identity was reused with different inputs")
                return False, self._rpc_snapshot(row)
            # Expired identities are rejected at the transport boundary before this cleanup.
            await db.execute("DELETE FROM plugin_rpc_receipts WHERE issued_at_ms < ?", (now - 7 * 86400000,))
            count, size = await (await db.execute(
                "SELECT COUNT(*), COALESCE(SUM(LENGTH(CAST(result_json AS BLOB))),0) FROM plugin_rpc_receipts"
            )).fetchone()
            if count >= 4096 or size >= 64 * 1024 * 1024:
                raise RuntimeError("Plugin request receipt capacity is exhausted")
            await db.execute(
                "INSERT INTO plugin_rpc_receipts (client_id,data_epoch,operation_id,fingerprint,issued_at_ms,owner,state,connection_id) VALUES (?,?,?,?,?,?,'running',?)",
                (client_id, epoch, operation_id, fingerprint, issued_at_ms, self.rpc_owner, connection_id),
            )
            key = (client_id, epoch, operation_id)
            self.rpc_active.add(key)
            try:
                await db.commit()
            except BaseException:
                self.rpc_active.discard(key)
                raise
            return True, {"operation_id": operation_id, "state": "running", "http_status": None, "result": None}

    def _rpc_snapshot(self, row: aiosqlite.Row) -> dict[str, Any]:
        state = row["state"]
        if state == "running" and (row["owner"] != self.rpc_owner or
            (row["client_id"], row["data_epoch"], row["operation_id"]) not in self.rpc_active):
            state = "uncertain"
        return {"operation_id": row["operation_id"], "state": state,
                "http_status": row["http_status"],
                "result": json.loads(row["result_json"]) if row["result_json"] else None}

    async def read_plugin_rpc(self, client_id: str, epoch: str, operation_id: str) -> dict[str, Any] | None:
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute(
                "SELECT * FROM plugin_rpc_receipts WHERE client_id=? AND data_epoch=? AND operation_id=?",
                (client_id, epoch, operation_id),
            )).fetchone()
            return self._rpc_snapshot(row) if row else None

    async def finish_plugin_rpc(
        self, *, client_id: str, epoch: str, operation_id: str,
        http_status: int | None, result: Any, connection_id: str | None,
    ) -> None:
        encoded = json.dumps(result, ensure_ascii=False) if http_status is not None else None
        if encoded is not None and len(encoded.encode()) > 256 * 1024:
            http_status, encoded = None, None
        try:
            async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
                await db.execute("PRAGMA synchronous=FULL")
                await db.execute("BEGIN IMMEDIATE")
                size = (await (await db.execute("SELECT COALESCE(SUM(LENGTH(CAST(result_json AS BLOB))),0) FROM plugin_rpc_receipts")).fetchone())[0]
                if size + len((encoded or "").encode()) > 64 * 1024 * 1024:
                    http_status, encoded = None, None
                await db.execute(
                    "UPDATE plugin_rpc_receipts SET state=?,http_status=?,result_json=?,connection_id=COALESCE(?,connection_id) WHERE client_id=? AND data_epoch=? AND operation_id=? AND owner=? AND state='running'",
                    ("completed" if http_status is not None else "uncertain", http_status, encoded,
                     connection_id, client_id, epoch, operation_id, self.rpc_owner),
                )
                await db.commit()
        finally:
            self.rpc_active.discard((client_id, epoch, operation_id))

    async def forget_connection_rpc_results(self, connection_id: str) -> None:
        """Erase private results while keeping a tombstone against duplicate execution."""
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            await db.execute("PRAGMA secure_delete=ON")
            await db.execute(
                "UPDATE plugin_rpc_receipts SET result_json=NULL,http_status=NULL,state='uncertain' WHERE connection_id=?",
                (connection_id,),
            )
            await db.commit()
