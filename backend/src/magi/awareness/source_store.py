"""Host-owned source revisions, resource references, and accepted checkpoints.

This fresh store is an ingestion journal, not a replacement for memory. A batch
can advance its checkpoint only after every upsert has a governed L1 receipt.
Source deletes retire the current object; they do not express user forgetting.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from magi_plugin_sdk.runtime import InvocationIdentity, PluginConnection, ResourceRef, SourceChange, SourceChangeBatch

from ..core.sqlite import sqlite_connection_async


_SCHEMA = """
CREATE TABLE IF NOT EXISTS source_connections (
    connection_id TEXT PRIMARY KEY,
    plugin_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    disconnected INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS source_checkpoints (
    connection_id TEXT NOT NULL REFERENCES source_connections(connection_id),
    source_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    cursor TEXT,
    revision INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (connection_id, source_id)
);
CREATE TABLE IF NOT EXISTS source_batches (
    batch_id TEXT PRIMARY KEY,
    connection_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    checkpoint_revision INTEGER NOT NULL,
    body TEXT NOT NULL,
    UNIQUE (connection_id, source_id),
    FOREIGN KEY (connection_id, source_id)
        REFERENCES source_checkpoints(connection_id, source_id)
);
CREATE TABLE IF NOT EXISTS source_resources (
    resource_id TEXT PRIMARY KEY,
    connection_id TEXT NOT NULL REFERENCES source_connections(connection_id),
    reference_json TEXT NOT NULL,
    content BLOB NOT NULL,
    is_evidence INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS source_versions (
    connection_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    object_id TEXT NOT NULL,
    version TEXT NOT NULL,
    operation TEXT NOT NULL CHECK(operation IN ('upsert', 'delete')),
    digest TEXT NOT NULL,
    evidence_id TEXT,
    receipt_json TEXT,
    accepted INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(connection_id, source_id, object_id, version),
    FOREIGN KEY (connection_id, source_id)
        REFERENCES source_checkpoints(connection_id, source_id)
);
CREATE TABLE IF NOT EXISTS source_objects (
    connection_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    object_id TEXT NOT NULL,
    version TEXT NOT NULL,
    deleted INTEGER NOT NULL,
    PRIMARY KEY(connection_id, source_id, object_id),
    FOREIGN KEY (connection_id, source_id, object_id, version)
        REFERENCES source_versions(connection_id, source_id, object_id, version)
);
CREATE TABLE IF NOT EXISTS source_resource_owners (
    connection_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    object_id TEXT NOT NULL,
    version TEXT NOT NULL,
    resource_id TEXT NOT NULL REFERENCES source_resources(resource_id) ON DELETE CASCADE,
    PRIMARY KEY(connection_id, source_id, object_id, version, resource_id)
);
"""


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def source_object_identity(connection_id: str, source_id: str, object_id: str) -> str:
    """Use unambiguous host namespacing while retaining the semantic source type."""
    return "source:" + hashlib.sha256(_json([connection_id, source_id, object_id]).encode()).hexdigest()


def source_change_digest(change: SourceChange) -> str:
    return hashlib.sha256(_json(change.model_dump(mode="json")).encode()).hexdigest()


class SourceCheckpointConflict(RuntimeError):
    """The batch's connection or checkpoint changed after collection started."""


@dataclass(frozen=True, slots=True)
class SourceCheckpoint:
    connection_id: str
    source_id: str
    source_type: str
    cursor: str | None
    revision: int


@dataclass(frozen=True, slots=True)
class PendingSourceBatch:
    batch_id: str
    checkpoint: SourceCheckpoint
    batch: SourceChangeBatch


class SourceStore:
    """Persist source data only behind host-issued connection authority.

    Callers hold the existing plugin runtime operation guard through collection,
    staging, governed memory ingestion, and acceptance. Clear callers hold its
    exclusive global clear boundary; checkpoint revisions fence stale batches.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        async with sqlite_connection_async(self.db_path) as db:
            await db.executescript(_SCHEMA)
            await db.commit()
        self._initialized = True

    async def _admit_connection(self, db: Any, connection: PluginConnection) -> None:
        if not connection.enabled:
            raise PermissionError("Source connection is disabled")
        rows = await db.execute_fetchall(
            "SELECT plugin_id, revision, disconnected FROM source_connections WHERE connection_id = ?",
            (connection.connection_id,),
        )
        if rows and (rows[0][0] != connection.plugin_id or rows[0][2] or rows[0][1] > connection.revision):
            raise SourceCheckpointConflict("Source connection is revoked or stale")
        await db.execute(
            "INSERT INTO source_connections(connection_id, plugin_id, revision) VALUES (?, ?, ?) "
            "ON CONFLICT(connection_id) DO UPDATE SET revision = excluded.revision",
            (connection.connection_id, connection.plugin_id, connection.revision),
        )

    async def checkpoint(
        self, connection: PluginConnection, source_id: str, source_type: str
    ) -> SourceCheckpoint:
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            await self._admit_connection(db, connection)
            await db.execute(
                "INSERT OR IGNORE INTO source_checkpoints(connection_id, source_id, source_type) VALUES (?, ?, ?)",
                (connection.connection_id, source_id, source_type),
            )
            rows = await db.execute_fetchall(
                "SELECT source_type, cursor, revision FROM source_checkpoints WHERE connection_id = ? AND source_id = ?",
                (connection.connection_id, source_id),
            )
            if rows[0][0] != source_type:
                raise ValueError("A registered source cannot change its semantic type")
            await db.commit()
            return SourceCheckpoint(connection.connection_id, source_id, source_type, rows[0][1], rows[0][2])

    async def pending(self, checkpoint: SourceCheckpoint) -> PendingSourceBatch | None:
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            rows = await db.execute_fetchall(
                "SELECT batch_id, checkpoint_revision, body FROM source_batches WHERE connection_id = ? AND source_id = ?",
                (checkpoint.connection_id, checkpoint.source_id),
            )
            if not rows:
                return None
            if rows[0][1] != checkpoint.revision:
                raise SourceCheckpointConflict("Pending batch checkpoint is stale")
            return PendingSourceBatch(rows[0][0], checkpoint, SourceChangeBatch.model_validate_json(rows[0][2]))

    async def register_resource(
        self,
        connection: PluginConnection,
        content: bytes,
        *,
        media_type: str,
        display_name: str = "",
    ) -> ResourceRef:
        """Mint an opaque reference from host-received bytes, never a plugin path."""
        if len(content) > 16 * 1024 * 1024:
            raise ValueError("Source resource exceeds the host size limit")
        ref = ResourceRef(
            resource_id="resource:" + uuid.uuid4().hex,
            connection_id=connection.connection_id,
            media_type=media_type,
            size_bytes=len(content),
            version=hashlib.sha256(content).hexdigest(),
            display_name=display_name,
        )
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            await self._admit_connection(db, connection)
            await db.execute(
                "INSERT INTO source_resources(resource_id, connection_id, reference_json, content) VALUES (?, ?, ?, ?)",
                (ref.resource_id, connection.connection_id, ref.model_dump_json(), content),
            )
            await db.commit()
        return ref

    @staticmethod
    async def _validate_resource(db: Any, connection_id: str, ref: ResourceRef) -> bytes:
        if ref.connection_id != connection_id:
            raise PermissionError("Source resource belongs to another connection")
        rows = await db.execute_fetchall(
            "SELECT reference_json, content FROM source_resources WHERE resource_id = ? AND connection_id = ?",
            (ref.resource_id, connection_id),
        )
        if not rows or ResourceRef.model_validate_json(rows[0][0]) != ref:
            raise PermissionError("Source resource is unknown, revoked, or has a different revision")
        return bytes(rows[0][1])

    async def read_resource(self, connection: PluginConnection, ref: ResourceRef) -> bytes:
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            await self._admit_connection(db, connection)
            content = await self._validate_resource(db, connection.connection_id, ref)
            await db.commit()
            return content

    async def validate_operation_resource(self, identity: InvocationIdentity, ref: ResourceRef) -> bool:
        """Validate an operation result against the persisted host resource ledger."""
        if identity.connection_id != ref.connection_id:
            return False
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            rows = await db.execute_fetchall(
                "SELECT r.reference_json FROM source_resources r JOIN source_connections c "
                "ON c.connection_id = r.connection_id WHERE r.resource_id = ? AND r.connection_id = ? "
                "AND c.plugin_id = ? AND c.disconnected = 0",
                (ref.resource_id, identity.connection_id, identity.plugin_id),
            )
            return bool(rows and ResourceRef.model_validate_json(rows[0][0]) == ref)

    async def stage_batch(
        self, connection: PluginConnection, checkpoint: SourceCheckpoint, batch: SourceChangeBatch
    ) -> PendingSourceBatch:
        """Journal a whole batch without advancing its authoritative cursor."""
        if not isinstance(batch, SourceChangeBatch):
            raise TypeError("Sources must return SourceChangeBatch")
        if checkpoint.connection_id != connection.connection_id:
            raise PermissionError("Source checkpoint connection mismatch")
        serialized = batch.model_dump_json()
        if len(serialized.encode()) > 32 * 1024 * 1024:
            raise ValueError("Source batch exceeds the host size limit")
        seen: set[tuple[str, str]] = set()
        for change in batch.changes:
            key = (change.object_id, change.version)
            if key in seen:
                raise ValueError("A batch must contain each object revision at most once")
            seen.add(key)
            if change.operation == "delete" and (change.payload or change.resources):
                raise ValueError("Source deletions cannot contain payloads or resources")
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            await self._admit_connection(db, connection)
            await self._check_checkpoint(db, checkpoint)
            previous = await db.execute_fetchall(
                "SELECT batch_id, body FROM source_batches WHERE connection_id = ? AND source_id = ?",
                (connection.connection_id, checkpoint.source_id),
            )
            if previous:
                if previous[0][1] != serialized:
                    raise SourceCheckpointConflict("A source batch is still awaiting memory acceptance")
                return PendingSourceBatch(previous[0][0], checkpoint, SourceChangeBatch.model_validate_json(serialized))
            for change in batch.changes:
                await self._stage_change(db, checkpoint, change)
            batch_id = uuid.uuid4().hex
            await db.execute(
                "INSERT INTO source_batches VALUES (?, ?, ?, ?, ?)",
                (batch_id, connection.connection_id, checkpoint.source_id, checkpoint.revision, serialized),
            )
            await db.commit()
        return PendingSourceBatch(batch_id, checkpoint, SourceChangeBatch.model_validate_json(serialized))

    async def _stage_change(self, db: Any, checkpoint: SourceCheckpoint, change: SourceChange) -> None:
        key = (checkpoint.connection_id, checkpoint.source_id, change.object_id, change.version)
        digest = source_change_digest(change)
        existing = await db.execute_fetchall(
            "SELECT digest FROM source_versions WHERE connection_id = ? AND source_id = ? AND object_id = ? AND version = ?",
            key,
        )
        if existing:
            if existing[0][0] != digest:
                raise ValueError("A source object revision cannot be reused for different content")
            return
        for ref in change.resources:
            await self._validate_resource(db, checkpoint.connection_id, ref)
        evidence_id = None
        if change.operation == "upsert":
            evidence_id = "evidence:" + uuid.uuid4().hex
            content = _json(change.payload).encode()
            ref = ResourceRef(
                resource_id=evidence_id, connection_id=checkpoint.connection_id,
                media_type="application/json", size_bytes=len(content), version=change.version,
            )
            await db.execute(
                "INSERT INTO source_resources VALUES (?, ?, ?, ?, 1)",
                (evidence_id, checkpoint.connection_id, ref.model_dump_json(), content),
            )
        await db.execute(
            "INSERT INTO source_versions(connection_id, source_id, object_id, version, operation, digest, evidence_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (*key, change.operation, digest, evidence_id),
        )
        for ref in change.resources:
            await db.execute("INSERT INTO source_resource_owners VALUES (?, ?, ?, ?, ?)", (*key, ref.resource_id))

    @staticmethod
    async def _check_checkpoint(db: Any, checkpoint: SourceCheckpoint) -> None:
        rows = await db.execute_fetchall(
            "SELECT revision, cursor FROM source_checkpoints WHERE connection_id = ? AND source_id = ?",
            (checkpoint.connection_id, checkpoint.source_id),
        )
        if not rows or rows[0][0] != checkpoint.revision or rows[0][1] != checkpoint.cursor:
            raise SourceCheckpointConflict("Source checkpoint changed during collection")

    async def version(self, checkpoint: SourceCheckpoint, change: SourceChange) -> dict[str, Any]:
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            rows = await db.execute_fetchall(
                "SELECT * FROM source_versions WHERE connection_id = ? AND source_id = ? AND object_id = ? AND version = ?",
                (checkpoint.connection_id, checkpoint.source_id, change.object_id, change.version),
            )
            if not rows:
                raise SourceCheckpointConflict("Source revision was cleared before ingestion")
            row = dict(rows[0])
            row["receipt"] = json.loads(row.pop("receipt_json")) if row["receipt_json"] else None
            if row["evidence_id"]:
                resources = await db.execute_fetchall(
                    "SELECT reference_json FROM source_resources WHERE resource_id = ?", (row["evidence_id"],)
                )
                row["evidence_ref"] = ResourceRef.model_validate_json(resources[0][0]) if resources else None
            return row

    async def record_receipt(
        self, pending: PendingSourceBatch, change: SourceChange, *, event_id: str, outcome: str
    ) -> None:
        if outcome not in {"persisted", "duplicate", "governed_skip"} or not event_id:
            raise ValueError("Source acceptance requires a terminal memory receipt")
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            await self._check_checkpoint(db, pending.checkpoint)
            key = (pending.checkpoint.connection_id, pending.checkpoint.source_id, change.object_id, change.version)
            await db.execute(
                "UPDATE source_versions SET receipt_json = ? WHERE connection_id = ? AND source_id = ? AND object_id = ? AND version = ?",
                (_json({"event_id": event_id, "outcome": outcome}), *key),
            )
            if outcome == "governed_skip":
                await db.execute(
                    "DELETE FROM source_resources WHERE resource_id IN (SELECT evidence_id FROM source_versions "
                    "WHERE connection_id = ? AND source_id = ? AND object_id = ? AND version = ?)", key,
                )
                await self._revoke_owned_resources(db, key)
                rows = await db.execute_fetchall("SELECT body FROM source_batches WHERE batch_id = ?", (pending.batch_id,))
                if rows:
                    body = json.loads(rows[0][0])
                    for item in body["changes"]:
                        if (item["object_id"], item["version"]) == (change.object_id, change.version):
                            item["payload"] = {}
                            item["resources"] = []
                    await db.execute("UPDATE source_batches SET body = ? WHERE batch_id = ?", (_json(body), pending.batch_id))
            await db.commit()

    async def attach_resource(self, checkpoint: SourceCheckpoint, change: SourceChange, ref: ResourceRef) -> None:
        """Track resources materialized while building the memory projection."""
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            await self._check_checkpoint(db, checkpoint)
            await self._validate_resource(db, checkpoint.connection_id, ref)
            await db.execute(
                "INSERT OR IGNORE INTO source_resource_owners VALUES (?, ?, ?, ?, ?)",
                (checkpoint.connection_id, checkpoint.source_id, change.object_id, change.version, ref.resource_id),
            )
            await db.commit()

    @staticmethod
    async def _revoke_owned_resources(db: Any, key: tuple[str, ...]) -> None:
        where = "connection_id = ? AND source_id = ? AND object_id = ?"
        if len(key) == 4:
            where += " AND version = ?"
        rows = await db.execute_fetchall(f"SELECT resource_id FROM source_resource_owners WHERE {where}", key)
        await db.execute(f"DELETE FROM source_resource_owners WHERE {where}", key)
        for row in rows:
            await db.execute(
                "DELETE FROM source_resources WHERE resource_id = ? AND NOT EXISTS "
                "(SELECT 1 FROM source_resource_owners WHERE resource_id = ?)", (row[0], row[0]),
            )

    async def accept_batch(self, connection: PluginConnection, pending: PendingSourceBatch) -> SourceCheckpoint:
        """Commit object transitions and cursor progression in one transaction."""
        checkpoint = pending.checkpoint
        if connection.connection_id != checkpoint.connection_id:
            raise PermissionError("Source batch connection mismatch")
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            await self._admit_connection(db, connection)
            await self._check_checkpoint(db, checkpoint)
            rows = await db.execute_fetchall(
                "SELECT body FROM source_batches WHERE batch_id = ? AND connection_id = ? AND source_id = ? AND checkpoint_revision = ?",
                (pending.batch_id, checkpoint.connection_id, checkpoint.source_id, checkpoint.revision),
            )
            if not rows:
                raise SourceCheckpointConflict("Source batch was cleared before acceptance")
            batch = SourceChangeBatch.model_validate_json(rows[0][0])
            for change in batch.changes:
                key = (checkpoint.connection_id, checkpoint.source_id, change.object_id, change.version)
                versions = await db.execute_fetchall(
                    "SELECT receipt_json, accepted FROM source_versions WHERE connection_id = ? AND source_id = ? AND object_id = ? AND version = ?", key,
                )
                if not versions or (change.operation == "upsert" and not versions[0][0]):
                    raise RuntimeError("Source batch has an unconfirmed memory revision")
                if versions[0][1]:
                    continue
                await db.execute(
                    "INSERT INTO source_objects VALUES (?, ?, ?, ?, ?) ON CONFLICT(connection_id, source_id, object_id) "
                    "DO UPDATE SET version = excluded.version, deleted = excluded.deleted",
                    (*key, int(change.operation == "delete")),
                )
                await db.execute(
                    "UPDATE source_versions SET accepted = 1 WHERE connection_id = ? AND source_id = ? AND object_id = ? AND version = ?", key,
                )
                if change.operation == "delete":
                    await self._revoke_owned_resources(db, key[:3])
            await db.execute(
                "UPDATE source_checkpoints SET cursor = ?, revision = revision + 1 WHERE connection_id = ? AND source_id = ?",
                (batch.next_cursor, checkpoint.connection_id, checkpoint.source_id),
            )
            await db.execute("DELETE FROM source_batches WHERE batch_id = ?", (pending.batch_id,))
            await db.commit()
        return SourceCheckpoint(checkpoint.connection_id, checkpoint.source_id, checkpoint.source_type, batch.next_cursor, checkpoint.revision + 1)

    async def current_object(self, checkpoint: SourceCheckpoint, object_id: str) -> dict[str, Any] | None:
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            rows = await db.execute_fetchall(
                "SELECT * FROM source_objects WHERE connection_id = ? AND source_id = ? AND object_id = ?",
                (checkpoint.connection_id, checkpoint.source_id, object_id),
            )
            return dict(rows[0]) if rows else None

    async def accepted_memory_event_ids(self, *, connection_id: str, source_type: str) -> list[str]:
        """Read receipt identities; callers must still apply memory visibility."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            rows = await db.execute_fetchall(
                "SELECT DISTINCT json_extract(v.receipt_json, '$.event_id') FROM source_versions v "
                "JOIN source_checkpoints c ON c.connection_id = v.connection_id AND c.source_id = v.source_id "
                "JOIN source_connections owner ON owner.connection_id = c.connection_id "
                "WHERE c.connection_id = ? AND c.source_type = ? AND owner.disconnected = 0 "
                "AND v.accepted = 1 AND json_extract(v.receipt_json, '$.outcome') IN ('persisted', 'duplicate')",
                (connection_id, source_type),
            )
            return [row[0] for row in rows if row[0]]

    async def clear_user_content(self, *, connection_id: str | None = None) -> None:
        """Erase content under the host's global clear barrier; retain progress."""
        await self.initialize()
        where = " WHERE connection_id = ?" if connection_id is not None else ""
        args = (connection_id,) if connection_id is not None else ()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute_fetchall("PRAGMA secure_delete = ON")
            await db.execute("BEGIN IMMEDIATE")
            for table in ("source_batches", "source_objects", "source_resource_owners", "source_versions", "source_resources"):
                await db.execute(f"DELETE FROM {table}{where}", args)
            await db.execute(f"UPDATE source_checkpoints SET revision = revision + 1{where}", args)
            await db.commit()
            await self._truncate_wal(db)
            await db.execute("VACUUM")
            await self._truncate_wal(db)

    @staticmethod
    async def _truncate_wal(db: Any) -> None:
        rows = await db.execute_fetchall("PRAGMA wal_checkpoint(TRUNCATE)")
        if rows and rows[0][0] != 0:
            raise RuntimeError("Source resource WAL could not be securely truncated")

    async def disconnect_connection(self, connection_id: str) -> None:
        """Revoke the instance before clearing its content so stale jobs fail."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("UPDATE source_connections SET disconnected = 1 WHERE connection_id = ?", (connection_id,))
            await db.commit()
        await self.clear_user_content(connection_id=connection_id)


__all__ = ["SourceStore", "SourceCheckpoint", "SourceCheckpointConflict", "PendingSourceBatch", "source_object_identity", "source_change_digest"]
