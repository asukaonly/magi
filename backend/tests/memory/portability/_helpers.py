from __future__ import annotations

from contextlib import asynccontextmanager
import hashlib
import json
import sqlite3
from typing import AsyncIterator

from magi.db.runner import MIGRATION_TARGETS, run_upgrade_head
from magi.utils.runtime import RuntimePaths


class FakeL0:
    def __init__(self) -> None:
        self.checkpoint_calls = 0

    async def checkpoint_all(self) -> None:
        self.checkpoint_calls += 1


class FakeUnifiedMemory:
    def __init__(self) -> None:
        self.guard_entries = 0
        self.l0 = FakeL0()

    @asynccontextmanager
    async def memory_maintenance_guard(self) -> AsyncIterator[None]:
        self.guard_entries += 1
        yield


def migrate_memory_databases(paths: RuntimePaths) -> None:
    selected = tuple(
        target for target in MIGRATION_TARGETS if target.name in {"l1", "memory_shared"}
    )
    run_upgrade_head(paths, targets=selected)


def seed_memory(paths: RuntimePaths) -> tuple[str, bytes]:
    asset_bytes = b"referenced-private-image"
    digest = hashlib.sha256(asset_bytes).hexdigest()
    asset_ref = f"manual-entry-asset://{digest}.png"
    asset_path = paths.manual_entry_assets_dir / digest[:2] / f"{digest}.png"
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    asset_path.write_bytes(asset_bytes)

    orphan_bytes = b"orphan-private-image"
    orphan_digest = hashlib.sha256(orphan_bytes).hexdigest()
    orphan_path = paths.manual_entry_assets_dir / orphan_digest[:2] / f"{orphan_digest}.png"
    orphan_path.parent.mkdir(parents=True, exist_ok=True)
    orphan_path.write_bytes(orphan_bytes)

    with sqlite3.connect(paths.l1_memory_db_path) as connection:
        connection.execute("""
            INSERT INTO fact_events(
                event_id, timestamp, created_at, event_type, source, memory_domain,
                content, author_type, content_type
            ) VALUES ('event-1', 1, 1, 'manual_entry', 'manual_entry', 1, 'hello', 1, 1)
            """)
        connection.execute("""
            INSERT INTO chat_sessions(
                session_id, user_id, title, title_overridden, summary, created_at,
                updated_at, last_message_preview, last_user_message_preview, message_count
            ) VALUES ('chat-secret', 'user', 'private chat', 0, '', 1, 1, '', '', 0)
            """)
        connection.commit()

    with sqlite3.connect(paths.memory_db_path) as connection:
        connection.execute("""
            INSERT INTO l0_sessions(
                session_id, user_id, status, started_at, last_active_at, metadata
            ) VALUES ('session-1', 'user', 'active', 1, 1, '{"secret":"short term"}')
            """)
        connection.execute("""
            INSERT INTO l0_attention_items(
                item_id, session_id, kind, summary, status, salience, confidence,
                evidence_mode, source_turn_ids, first_seen_at, last_reinforced_at, metadata
            ) VALUES (
                'attention-1', 'session-1', 'topic', 'short term secret', 'active',
                1, 1, 'explicit', '["chat-turn-secret"]', 1, 1, '{}'
            )
            """)
        connection.execute("""
            INSERT INTO l0_forgotten_attention_source_refs(source_ref, created_at)
            VALUES ('turn:forgotten', 1)
            """)
        connection.execute(
            """
            INSERT INTO manual_entries(entry_id, created_at, event_at, body, attachments_json)
            VALUES ('entry-1', 1, 1, 'a memory', ?)
            """,
            (json.dumps([asset_ref]),),
        )
        connection.execute("""
            INSERT INTO history_import_jobs(
                job_id, source_type, source_fingerprint, detected_kind, status,
                created_at, updated_at
            ) VALUES ('import-1', 'chat_export', 'fingerprint', 'chat', 'succeeded', 1, 1)
            """)
        connection.execute("""
            INSERT INTO history_import_source_records(
                source_record_key, file_fingerprint, source_name, parsed_session_key,
                session_id, session_seq, speaker_name, content, event_at,
                timestamp_confidence, timestamp_anchor_source, calendar_timezone_id,
                event_id, created_at
            ) VALUES (
                'source-1', 'file-1', 'import.json', 'parsed-1', 'import-session', 1,
                'speaker', 'raw imported transcript secret', 1, 'exact', 'source',
                'UTC', 'import-event-1', 1
            )
            """)
        connection.execute("""
            INSERT INTO history_import_job_records(
                job_record_id, job_id, source_record_key, raw_state, projection_state,
                created_at, updated_at
            ) VALUES ('job-record-1', 'import-1', 'source-1', 'stored', 'projected', 1, 1)
            """)
        connection.commit()
    return digest, orphan_digest.encode("ascii")


__all__ = ["FakeUnifiedMemory", "migrate_memory_databases", "seed_memory"]
