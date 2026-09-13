"""Atomic device checkpoints and bounded reliable observation delivery."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
import sqlite3
import time
from uuid import uuid4

from magi_plugin_sdk.runtime import SourceChangeBatch


class CollectorQueue:
    MAX_ROWS = 10000
    MAX_BYTES = 64 * 1024 * 1024

    def __init__(self, path: Path, identity: dict[str, str]) -> None:
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA secure_delete=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), identity TEXT NOT NULL,
                producer TEXT NOT NULL, position INTEGER NOT NULL, checkpoint TEXT, last_success REAL);
            CREATE TABLE IF NOT EXISTS observations (object_id TEXT PRIMARY KEY, version TEXT NOT NULL, digest TEXT NOT NULL, position INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS events (sequence INTEGER PRIMARY KEY, event TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0, retry_at REAL NOT NULL DEFAULT 0,
                failure TEXT, terminal INTEGER NOT NULL DEFAULT 0);
        """)
        encoded = json.dumps(identity, sort_keys=True)
        row = self.db.execute("SELECT identity FROM state").fetchone()
        if row and row[0] != encoded:
            self.db.close()
            raise ValueError("Collector identity or configuration changed; use a new data directory")
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO state VALUES (1,?,?,0,NULL,NULL)", (encoded, str(uuid4())))

    def state(self) -> sqlite3.Row:
        return self.db.execute("SELECT * FROM state").fetchone()

    def append(self, batch: SourceChangeBatch, scope: dict[str, str]) -> None:
        """Advance the checkpoint only in the transaction that stores every collected fact."""
        with self.db:
            state = self.state()
            position = state["position"]
            rows = []
            for change in batch.changes:
                if change.resources:
                    raise ValueError("Remote collection does not accept resource references")
                digest = hashlib.sha256(json.dumps(change.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                previous = self.db.execute("SELECT version,digest FROM observations WHERE object_id=?", (change.object_id,)).fetchone()
                if previous and previous[0] == change.version:
                    if previous[1] != digest:
                        raise ValueError("Source reused an object revision for different content")
                    continue
                position += 1
                self.db.execute("INSERT OR REPLACE INTO observations VALUES (?,?,?,?)", (change.object_id, change.version, digest, position))
                payload = {"kind": "plugin_event", "connection_id": scope["connection_id"],
                           "connection_epoch": scope["connection_epoch"], "plugin_target": scope["plugin_id"],
                           "event_type": "source.change.v1", "data": {"source_type": scope["source_type"],
                           "plugin_version": scope["plugin_version"], "source_change": change.model_dump(mode="json")}}
                if len(json.dumps(payload).encode()) > 65536:
                    raise ValueError("Collected observation exceeds the delivery limit")
                event = {"event_id": str(uuid4()), "stream": scope["source_type"], "sequence": position,
                         "occurred_at_ms": max(0, int((change.occurred_at or time.time()) * 1000)), "payload": payload}
                rows.append((position, json.dumps(event)))
            count, size = self.db.execute("SELECT COUNT(*),COALESCE(SUM(length(CAST(event AS BLOB))),0) FROM events").fetchone()
            if count + len(rows) > self.MAX_ROWS or size + sum(len(row[1].encode()) for row in rows) > self.MAX_BYTES:
                raise BufferError("Collector queue is full; checkpoint was retained")
            self.db.executemany("INSERT INTO events(sequence,event) VALUES (?,?)", rows)
            self.db.execute("DELETE FROM observations WHERE object_id IN (SELECT object_id FROM observations ORDER BY position DESC LIMIT -1 OFFSET 5000)")
            self.db.execute("UPDATE state SET position=?,checkpoint=?,last_success=?", (position, batch.next_cursor, time.time()))

    def head(self) -> sqlite3.Row | None:
        row = self.db.execute("SELECT * FROM events ORDER BY sequence LIMIT 1").fetchone()
        return row if row and not row["terminal"] and row["retry_at"] <= time.time() else None

    def acknowledge(self, sequence: int) -> None:
        with self.db:
            self.db.execute("DELETE FROM events WHERE sequence=?", (sequence,))

    def fail(self, sequence: int, code: str, *, terminal: bool = False) -> None:
        with self.db:
            row = self.db.execute("SELECT attempts FROM events WHERE sequence=?", (sequence,)).fetchone()
            if row is None:
                return
            attempts = row[0] + 1
            self.db.execute("UPDATE events SET attempts=?,retry_at=?,failure=?,terminal=? WHERE sequence=?",
                            (attempts, time.time() + min(300, 2 ** min(attempts, 9)), code, terminal, sequence))

    def recover(self, *, discard: bool = False) -> None:
        with self.db:
            if discard:
                self.db.execute("DELETE FROM events WHERE terminal=1")
            else:
                self.db.execute("UPDATE events SET terminal=0,attempts=0,retry_at=0,failure=NULL")
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def status(self) -> dict[str, object]:
        counts = self.db.execute("SELECT COUNT(*),COALESCE(SUM(terminal),0) FROM events").fetchone()
        row = self.db.execute("SELECT sequence,attempts,retry_at,failure,terminal FROM events ORDER BY sequence LIMIT 1").fetchone()
        return {"pending": counts[0], "failed": counts[1], "head": dict(row) if row else None}

    def close(self) -> None:
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.db.close()
