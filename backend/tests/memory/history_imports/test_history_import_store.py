"""Bounded identity reads against the migrated history-import database."""

from __future__ import annotations

import sqlite3
import aiosqlite
import pytest
from _shared.memory_schema import apply_memory_shared_schema
from magi.memory.history_imports.store import (
    _load_reserved_session_prefixes,
    _load_source_identity_rows,
)


class _BoundedDatabase:
    def __init__(self, db):
        self.db = db
        self.parameter_counts = []

    def execute(self, sql, parameters):
        self.parameter_counts.append(len(parameters))
        assert len(parameters) <= 999
        return self.db.execute(sql, parameters)


async def _seed_records(db, rows):
    await db.executemany(
        "INSERT INTO history_import_source_records(source_record_key, file_fingerprint, source_id, source_name, parsed_session_key, session_id, session_seq, speaker_name, content, event_at, timestamp_confidence, timestamp_anchor_source, calendar_timezone_id, event_id, message_key, created_at) VALUES (?, 'fingerprint', ?, 'Archive', ?, ?, ?, 'Owner', ?, 100.0, 'exact', 'source', 'UTC', ?, ?, 100.0)",
        [
            (
                key,
                source,
                session,
                "stored-" + session,
                sequence,
                "content-" + key,
                "event-" + key,
                message,
            )
            for key, source, session, sequence, message in rows
        ],
    )


@pytest.mark.asyncio
async def test_source_identity_rows_are_complete_and_bounded_across_real_sql_batches(tmp_path):
    path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(path)
    keys = [f"record-{index}" for index in range(805)]
    async with aiosqlite.connect(path) as db:
        db.row_factory = sqlite3.Row
        await _seed_records(
            db,
            [
                (key, f"source-{index}", f"session-{index}", index, f"message-{index}")
                for index, key in enumerate(keys + ["unrequested"])
            ],
        )
        bounded = _BoundedDatabase(db)
        loaded = await _load_source_identity_rows(bounded, [*keys, keys[0], "missing"])
        assert {
            key: (row["source_id"], row["parsed_session_key"], row["session_seq"], row["content"])
            for key, row in loaded.items()
        } == {
            key: (f"source-{index}", f"session-{index}", index, "content-" + key)
            for index, key in enumerate(keys)
        }
        assert len(bounded.parameter_counts) > 1
        assert sum(bounded.parameter_counts) == len(keys) + 1
        bounded.parameter_counts.clear()
        assert await _load_source_identity_rows(bounded, []) == {}
        assert bounded.parameter_counts == []


@pytest.mark.asyncio
async def test_reserved_prefixes_preserve_order_and_owner_across_real_sql_batches(tmp_path):
    path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(path)
    identities = [(f"source-{index}", f"session-{index}") for index in range(805)]
    async with aiosqlite.connect(path) as db:
        db.row_factory = sqlite3.Row
        jobs = [
            ("confirmed", "owner", "archive", "export", "1", "completed", None),
            ("other-connection", "other", "archive", "export", "1", "completed", None),
            ("other-plugin", "owner", "other", "export", "1", "completed", None),
            ("other-importer", "owner", "archive", "other", "1", "completed", None),
            ("other-version", "owner", "archive", "export", "2", "completed", None),
            ("preview", "owner", "archive", "export", "1", "preview_ready", None),
            ("deleted", "owner", "archive", "export", "1", "completed", 200.0),
        ]
        await db.executemany(
            "INSERT INTO history_import_jobs(job_id, source_type, source_fingerprint, detected_kind, status, created_at, updated_at, connection_id, importer_plugin_id, importer_id, importer_format_version, deleted_at) VALUES (?, 'history_import', ?, 'chat', ?, 100, 100, ?, ?, ?, ?, ?)",
            [
                (job, job, status, connection, plugin, importer, version, deleted)
                for job, connection, plugin, importer, version, status, deleted in jobs
            ],
        )
        rows = [
            (f"record-{index}", source, session, 1, f"message-{index}")
            for index, (source, session) in enumerate(identities)
        ]
        rows += [
            ("earlier", *identities[0], 0, "first-message"),
            ("skipped", *identities[0], 2, "skipped-message"),
            ("other-session", identities[0][0], "unrequested-session", 3, "other-session-message"),
        ]
        rows += [(job, *identities[0], 4, job + "-message") for job, *_ in jobs[1:]]
        await _seed_records(db, rows)
        memberships = [
            ("confirmed", key, sequence, "skipped" if key == "skipped" else "pending")
            for key, _, _, sequence, _ in rows
            if key not in {job[0] for job in jobs[1:]}
        ]
        memberships += [(job, job, 4, "pending") for job, *_ in jobs[1:]]
        await db.executemany(
            "INSERT INTO history_import_job_records(job_record_id, job_id, source_record_key, source_order, raw_state, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 100, 100)",
            [(job + ":" + key, job, key, order, state) for job, key, order, state in memberships],
        )
        bounded = _BoundedDatabase(db)
        loaded = await _load_reserved_session_prefixes(
            bounded,
            connection_id="owner",
            importer_plugin_id="archive",
            importer_id="export",
            importer_format_version="1",
            session_identities=[*identities, identities[0]],
        )
        expected = {identity: [f"message-{index}"] for index, identity in enumerate(identities)}
        expected[identities[0]].insert(0, "first-message")
        assert loaded == expected
        assert len(bounded.parameter_counts) > 1
        assert sum(count - 4 for count in bounded.parameter_counts) == len(identities) * 2
