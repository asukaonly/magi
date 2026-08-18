from __future__ import annotations

from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import AsyncIterator

import pytest

from magi.db.runner import MIGRATION_TARGETS, run_upgrade_head
from magi.memory.portability.backup import build_memory_backup
from magi.memory.portability.preflight import (
    delete_restore_candidate,
    inspect_memory_backup,
    load_restore_candidate,
)
from magi.memory.portability.restore import (
    ValidatedRestoreCandidate,
    prepare_memory_restore,
)
from magi.memory.portability.storage import (
    count_snapshot_records,
    create_memory_snapshot,
    discard_snapshot,
)
from magi.utils.runtime import RuntimePaths


class _CheckpointedMemory:
    def __init__(self) -> None:
        self.l0 = self
        self.checkpoints = 0

    @asynccontextmanager
    async def memory_maintenance_guard(self) -> AsyncIterator[None]:
        yield

    async def checkpoint_all(self) -> None:
        self.checkpoints += 1


def _migrate_memory_databases(paths: RuntimePaths) -> None:
    targets = tuple(
        target for target in MIGRATION_TARGETS if target.name in {"l1", "memory_shared"}
    )
    run_upgrade_head(paths, targets=targets)


def _write_private(path: Path, content: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_bytes(content)
    if os.name != "nt":
        path.parent.chmod(0o700)
        path.chmod(0o600)


def _create_archive(path: Path, *, marker: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE archived_l1_events (
                event_id TEXT PRIMARY KEY,
                archived_date TEXT NOT NULL,
                archived_at REAL NOT NULL,
                event_timestamp REAL NOT NULL,
                event_type TEXT NOT NULL,
                source TEXT NOT NULL,
                session_id TEXT,
                user_id TEXT,
                payload_json TEXT NOT NULL
            );
            CREATE INDEX idx_archived_l1_events_date
                ON archived_l1_events(archived_date, event_timestamp);
            CREATE TABLE archived_l3_summaries (
                summary_id TEXT PRIMARY KEY,
                archived_date TEXT NOT NULL,
                archived_at REAL NOT NULL,
                period_start REAL NOT NULL,
                period_end REAL NOT NULL,
                summary_type TEXT NOT NULL,
                summary_category TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE INDEX idx_archived_l3_summaries_date
                ON archived_l3_summaries(archived_date, period_end);
            """
        )
        connection.execute(
            """
            INSERT INTO archived_l1_events VALUES (
                ?, '2026-08-01', 1, 1, 'manual_entry', 'manual_entry',
                'session-roundtrip', 'user-roundtrip', ?
            )
            """,
            (f"archive-event-{marker}", json.dumps({"marker": marker})),
        )
        connection.execute(
            """
            INSERT INTO archived_l3_summaries VALUES (
                ?, '2026-08-01', 1, 1, 2, 'daily', 'general', ?
            )
            """,
            (f"archive-summary-{marker}", json.dumps({"marker": marker})),
        )
        connection.commit()
    if os.name != "nt":
        path.chmod(0o600)


def _seed_complete_memory(paths: RuntimePaths, archive_dir: Path) -> tuple[Path, bytes]:
    asset_bytes = b"roundtrip-visible-manual-asset"
    asset_digest = hashlib.sha256(asset_bytes).hexdigest()
    asset_ref = f"manual-entry-asset://{asset_digest}.png"
    asset_path = paths.manual_entry_assets_dir / asset_digest[:2] / f"{asset_digest}.png"
    _write_private(asset_path, asset_bytes)

    with sqlite3.connect(paths.l1_memory_db_path) as connection:
        connection.execute(
            """
            INSERT INTO fact_events(
                event_id, timestamp, created_at, event_type, source, memory_domain,
                session_id, user_id, content, author_type, content_type
            ) VALUES (
                'event-roundtrip', 1, 1, 'manual_entry', 'manual_entry', 1,
                'session-roundtrip', 'user-roundtrip', 'roundtrip l1 memory', 1, 1
            )
            """
        )
        connection.execute(
            """
            INSERT INTO l1_event_embedding_state(
                event_id, embedding_status, embedding_profile_id,
                embedding_chunk_count, last_embedded_at, updated_at
            ) VALUES ('event-roundtrip', 3, 'old-profile', 1, 1, 1)
            """
        )
        connection.execute(
            """
            INSERT INTO embedding_profiles(
                profile_id, provider_name, model_name, embedding_dim,
                text_builder_version, created_at
            ) VALUES ('old-profile', 'old-provider', 'old-model', 2, 'old-builder', 1)
            """
        )
        connection.execute(
            """
            INSERT INTO l1_event_chunks(
                chunk_id, event_id, chunk_index, chunk_text, char_start, char_end,
                token_estimate, embedding_profile_id, created_at, updated_at
            ) VALUES (
                'old-l1-chunk', 'event-roundtrip', 0, 'stale vector text',
                0, 17, 3, 'old-profile', 1, 1
            )
            """
        )
        connection.execute("DELETE FROM l1_events_fts")
        connection.execute(
            "INSERT INTO l1_events_fts(event_id, content) VALUES ('stale-event', 'stale')"
        )
        connection.commit()

    with sqlite3.connect(paths.memory_db_path) as connection:
        connection.executescript(
            """
            INSERT INTO l0_sessions(
                session_id, user_id, status, started_at, last_active_at, metadata
            ) VALUES (
                'session-roundtrip', 'user-roundtrip', 'active', 1, 2,
                '{"checkpoint":"persisted"}'
            );
            INSERT INTO l0_attention_items(
                item_id, session_id, kind, summary, status, salience, confidence,
                evidence_mode, source_turn_ids, source_event_ids,
                first_seen_at, last_reinforced_at, metadata
            ) VALUES (
                'attention-roundtrip', 'session-roundtrip', 'topic',
                'roundtrip attention', 'active', 0.9, 0.8, 'explicit',
                '["turn-roundtrip"]', '["event-roundtrip"]', 1, 2, '{}'
            );
            INSERT INTO l0_forgotten_attention_source_refs(source_ref, created_at)
            VALUES ('turn:forgotten-before-backup', 1);

            INSERT INTO entity_catalog(
                entity_id, canonical_name, entity_type, embedding_status,
                embedding_profile_id, last_embedded_at, created_at, updated_at
            ) VALUES
                ('entity-user', 'Roundtrip User', 'person', 'ready', 'old-profile', 1, 1, 1),
                ('entity-coffee', 'Coffee', 'concept', 'ready', 'old-profile', 1, 1, 1);
            INSERT INTO knowledge_graph(
                triple_id, subject_id, subject_type, predicate, object_id, object_type,
                evidence_event_ids, natural_summary, first_observed_at, last_observed_at,
                embedding_status, embedding_profile_id, last_embedded_at, status,
                created_at, updated_at, slot_key, claim_fingerprint
            ) VALUES
                (
                    'triple-active', 'entity-user', 'person', 'likes',
                    'entity-coffee', 'concept', '["event-roundtrip"]',
                    'The user likes coffee', 1, 2, 'ready', 'old-profile', 1,
                    'active', 1, 2, 'likes:coffee', 'claim-active'
                ),
                (
                    'triple-superseded', 'entity-user', 'person', 'avoids',
                    'entity-coffee', 'concept', '["event-roundtrip"]',
                    'An older relationship state', 1, 1, 'ready', 'old-profile', 1,
                    'superseded', 1, 2, 'avoids:coffee', 'claim-superseded'
                );
            INSERT INTO tom_trait_assertions(
                assertion_id, entity_id, entity_type, trait_family, trait_name,
                trait_value, confidence_score, evidence_events, volatility_index,
                source_domain, inference_depth, validation_state, first_inferred_at,
                last_validated_at, status, natural_summary, created_at, updated_at,
                slot_key, claim_fingerprint, semantic_lineage_key
            ) VALUES
                (
                    'assertion-active', 'entity-user', 'person', 'preference',
                    'drink', 'coffee', 0.9, '["event-roundtrip"]', 0.1,
                    'manual', 'explicit', 'confirmed', 1, 2, 'active',
                    'The user prefers coffee', 1, 2, 'preference:drink',
                    'assertion-claim-active', 'assertion-lineage-active'
                ),
                (
                    'assertion-superseded', 'entity-user', 'person', 'preference',
                    'old_drink', 'tea', 0.5, '["event-roundtrip"]', 0.1,
                    'manual', 'explicit', 'superseded', 1, 2, 'superseded',
                    'An older preference state', 1, 2, 'preference:old-drink',
                    'assertion-claim-superseded', 'assertion-lineage-superseded'
                );

            INSERT INTO episodes(
                episode_id, status, time_start, time_end, label, summary,
                primary_entity_ids, source_event_count, embedding_status,
                embedding_profile_id, last_embedded_at, created_at, updated_at,
                representative_asset_ref
            ) VALUES (
                'episode-roundtrip', 'confirmed', 1, 2, 'Roundtrip episode',
                'A complete roundtrip episode', '["entity-user"]', 1,
                'ready', 'old-profile', 1, 1, 2,
                'ASSET_REF_PLACEHOLDER'
            );
            INSERT INTO episode_events(
                episode_id, event_id, membership_role, membership_confidence, added_at
            ) VALUES ('episode-roundtrip', 'event-roundtrip', 'core', 1, 1);
            INSERT INTO experiences(
                experience_id, status, title, time_start, time_end, experience_type,
                outcome, primary_entity_ids, source_episode_count, source_event_count,
                created_at, updated_at, user_cover_asset_ref
            ) VALUES (
                'experience-roundtrip', 'confirmed', 'Roundtrip experience', 1, 2,
                'personal', 'restored', '["entity-user"]', 1, 1, 1, 2,
                'ASSET_REF_PLACEHOLDER'
            );
            INSERT INTO experience_members(
                experience_id, member_type, member_id, role, confidence, added_at
            ) VALUES (
                'experience-roundtrip', 'episode', 'episode-roundtrip', 'core', 1, 1
            );
            INSERT INTO experience_key_events(
                experience_id, event_id, role, reason, confidence, added_at
            ) VALUES (
                'experience-roundtrip', 'event-roundtrip', 'turning_point',
                'roundtrip evidence', 1, 1
            );

            INSERT INTO summaries(
                summary_id, summary_type, summary_category, period_start, period_end,
                content, source_event_ids, source_event_count, embedding_status,
                embedding_profile_id, embedding_chunk_count, last_embedded_at,
                created_at, updated_at
            ) VALUES (
                'summary-roundtrip', 'daily', 'general', 1, 2,
                'Roundtrip L3 summary', '["event-roundtrip"]', 1,
                'ready', 'old-profile', 1, 1, 1, 2
            );
            INSERT INTO summary_event_links(
                link_id, summary_id, event_id, link_role, evidence_weight, created_at
            ) VALUES (
                'summary-link-roundtrip', 'summary-roundtrip', 'event-roundtrip',
                'evidence', 1, 1
            );
            INSERT INTO l3_summary_chunks(
                chunk_id, summary_id, chunk_index, chunk_text, char_start, char_end,
                token_estimate, created_at, updated_at
            ) VALUES (
                'old-l3-chunk', 'summary-roundtrip', 0, 'stale summary vector',
                0, 20, 3, 1, 1
            );

            INSERT INTO procedural_skills(
                skill_id, skill_name, skill_category, skill_type, proficiency,
                total_attempts, success_count, success_rate, optimized_prompt,
                source_event_ids, embedding_status, embedding_profile_id,
                embedding_chunk_count, last_embedded_at, created_at, updated_at
            ) VALUES (
                'skill-roundtrip', 'Roundtrip procedure', 'workflow', 'learned', 0.8,
                1, 1, 1, 'Use the restored procedure', '["event-roundtrip"]',
                'ready', 'old-profile', 1, 1, 1, 2
            );
            INSERT INTO l4_skill_event_links(skill_id, event_id, created_at)
            VALUES ('skill-roundtrip', 'event-roundtrip', 1);
            INSERT INTO l4_skill_chunks(
                chunk_id, skill_id, chunk_index, chunk_text, char_start, char_end,
                token_estimate, created_at, updated_at
            ) VALUES (
                'old-l4-chunk', 'skill-roundtrip', 0, 'stale skill vector',
                0, 18, 3, 1, 1
            );

            INSERT INTO manual_entries(
                entry_id, created_at, event_at, body, attachments_json, l1_event_id
            ) VALUES (
                'entry-roundtrip', 1, 1, 'Roundtrip manual memory',
                '["ASSET_REF_PLACEHOLDER"]', 'event-roundtrip'
            );

            INSERT INTO embedding_rebuild_jobs(
                job_id, status, requested_layers_json, created_at, updated_at
            ) VALUES ('stale-rebuild-job', 'running', '["l1","l2"]', 1, 1);

            DELETE FROM episodes_fts;
            INSERT INTO episodes_fts(episode_id, summary, label, user_label)
            VALUES ('stale-episode', 'stale', 'stale', 'stale');
            DELETE FROM l3_summaries_fts;
            INSERT INTO l3_summaries_fts(summary_id, content)
            VALUES ('stale-summary', 'stale');
            DELETE FROM l4_skills_fts;
            INSERT INTO l4_skills_fts(skill_id, content)
            VALUES ('stale-skill', 'stale');
            """.replace("ASSET_REF_PLACEHOLDER", asset_ref)
        )
        connection.commit()

    archive_path = archive_dir / "2026-08-01.db"
    _create_archive(archive_path, marker="roundtrip")
    (archive_dir / "README.txt").write_text("unmanaged archive note", encoding="utf-8")
    return asset_path, asset_bytes


def _mutate_live_memory(paths: RuntimePaths, archive_dir: Path, *, attempt: int) -> None:
    live_asset_bytes = f"live-only-asset-{attempt}".encode()
    live_digest = hashlib.sha256(live_asset_bytes).hexdigest()
    live_ref = f"manual-entry-asset://{live_digest}.png"
    _write_private(
        paths.manual_entry_assets_dir / live_digest[:2] / f"{live_digest}.png",
        live_asset_bytes,
    )
    with sqlite3.connect(paths.l1_memory_db_path) as connection:
        connection.execute(
            "UPDATE fact_events SET content = ? WHERE event_id = 'event-roundtrip'",
            (f"mutated l1 memory {attempt}",),
        )
        connection.execute(
            """
            INSERT INTO fact_events(
                event_id, timestamp, created_at, event_type, source, memory_domain,
                content, author_type, content_type
            ) VALUES (?, 3, 3, 'manual_entry', 'manual_entry', 1, 'live only', 1, 1)
            """,
            (f"event-live-{attempt}",),
        )
        connection.commit()
    with sqlite3.connect(paths.memory_db_path) as connection:
        connection.execute(
            "UPDATE l0_attention_items SET summary = ? WHERE item_id = 'attention-roundtrip'",
            (f"mutated attention {attempt}",),
        )
        connection.execute(
            "UPDATE knowledge_graph SET status = 'superseded' WHERE triple_id = 'triple-active'"
        )
        connection.execute(
            "UPDATE summaries SET content = ? WHERE summary_id = 'summary-roundtrip'",
            (f"mutated summary {attempt}",),
        )
        connection.execute(
            "UPDATE procedural_skills SET optimized_prompt = ? WHERE skill_id = 'skill-roundtrip'",
            (f"mutated procedure {attempt}",),
        )
        connection.execute(
            "UPDATE manual_entries SET body = ? WHERE entry_id = 'entry-roundtrip'",
            (f"mutated manual memory {attempt}",),
        )
        connection.execute(
            """
            INSERT INTO manual_entries(
                entry_id, created_at, event_at, body, attachments_json
            ) VALUES (?, 3, 3, 'live only', ?)
            """,
            (f"entry-live-{attempt}", json.dumps([live_ref])),
        )
        connection.commit()
    (archive_dir / "2026-08-01.db").unlink()
    _create_archive(archive_dir / f"2026-08-0{attempt + 1}.db", marker=f"live-{attempt}")


def _assert_complete_restored_state(
    paths: RuntimePaths,
    archive_dir: Path,
    *,
    expected_counts: dict[str, int],
    asset_path: Path,
    asset_bytes: bytes,
) -> tuple[object, ...]:
    archive_path = archive_dir / "2026-08-01.db"
    counts = count_snapshot_records(
        paths.l1_memory_db_path,
        paths.memory_db_path,
        [archive_path],
    )
    counts["manual_entry_assets"] = len(
        [path for path in paths.manual_entry_assets_dir.rglob("*") if path.is_file()]
    )
    assert counts == expected_counts
    assert counts == {
        "l0_sessions": 1,
        "l0_attention_items": 1,
        "l1_events": 1,
        "l2_entities": 2,
        "l2_relationships": 1,
        "l2_assertions": 1,
        "l2_episodes": 1,
        "l2_experiences": 1,
        "manual_entries": 1,
        "l3_summaries": 1,
        "l4_procedures": 1,
        "archives": 1,
        "manual_entry_assets": 1,
    }

    with sqlite3.connect(paths.l1_memory_db_path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert connection.execute("PRAGMA foreign_key_check").fetchone() is None
        l1_rows = connection.execute(
            "SELECT event_id, content FROM fact_events ORDER BY event_id"
        ).fetchall()
        assert l1_rows == [("event-roundtrip", "roundtrip l1 memory")]
        assert connection.execute(
            """
            SELECT embedding_status, embedding_profile_id, embedding_chunk_count,
                   last_embedded_at
            FROM l1_event_embedding_state WHERE event_id = 'event-roundtrip'
            """
        ).fetchone() == (2, None, 0, None)
        assert connection.execute("SELECT COUNT(*) FROM embedding_profiles").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM l1_event_chunks").fetchone() == (0,)
        assert connection.execute(
            "SELECT event_id FROM l1_events_fts ORDER BY event_id"
        ).fetchall() == [("event-roundtrip",)]

    with sqlite3.connect(paths.memory_db_path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert connection.execute("PRAGMA foreign_key_check").fetchone() is None
        l0_state = connection.execute(
            """
            SELECT sessions.session_id, attention.item_id, attention.summary,
                   attention.status, attention.source_event_ids
            FROM l0_sessions AS sessions
            JOIN l0_attention_items AS attention USING(session_id)
            """
        ).fetchone()
        assert l0_state == (
            "session-roundtrip",
            "attention-roundtrip",
            "roundtrip attention",
            "active",
            '["event-roundtrip"]',
        )
        assert connection.execute(
            "SELECT source_ref FROM l0_forgotten_attention_source_refs"
        ).fetchall() == [("turn:forgotten-before-backup",)]
        assert connection.execute(
            "SELECT entity_id, canonical_name, embedding_status FROM entity_catalog ORDER BY entity_id"
        ).fetchall() == [
            ("entity-coffee", "Coffee", "pending"),
            ("entity-user", "Roundtrip User", "pending"),
        ]
        assert connection.execute(
            "SELECT triple_id, status, embedding_status FROM knowledge_graph ORDER BY triple_id"
        ).fetchall() == [
            ("triple-active", "active", "pending"),
            ("triple-superseded", "superseded", "pending"),
        ]
        assert connection.execute(
            "SELECT assertion_id, status FROM tom_trait_assertions ORDER BY assertion_id"
        ).fetchall() == [
            ("assertion-active", "active"),
            ("assertion-superseded", "superseded"),
        ]
        assert connection.execute(
            "SELECT episode_id, event_id, membership_role FROM episode_events"
        ).fetchall() == [("episode-roundtrip", "event-roundtrip", "core")]
        assert connection.execute(
            "SELECT experience_id, member_type, member_id FROM experience_members"
        ).fetchall() == [("experience-roundtrip", "episode", "episode-roundtrip")]
        assert connection.execute(
            "SELECT experience_id, event_id, role FROM experience_key_events"
        ).fetchall() == [("experience-roundtrip", "event-roundtrip", "turning_point")]
        assert connection.execute(
            "SELECT summary_id, event_id, link_role FROM summary_event_links"
        ).fetchall() == [("summary-roundtrip", "event-roundtrip", "evidence")]
        assert connection.execute(
            "SELECT skill_id, event_id FROM l4_skill_event_links"
        ).fetchall() == [("skill-roundtrip", "event-roundtrip")]
        assert connection.execute(
            "SELECT content, embedding_status, embedding_chunk_count FROM summaries"
        ).fetchall() == [("Roundtrip L3 summary", "pending", 0)]
        assert connection.execute(
            "SELECT optimized_prompt, embedding_status, embedding_chunk_count FROM procedural_skills"
        ).fetchall() == [("Use the restored procedure", "pending", 0)]
        assert connection.execute(
            "SELECT body, attachments_json FROM manual_entries"
        ).fetchone() == (
            "Roundtrip manual memory",
            json.dumps([f"manual-entry-asset://{asset_path.stem}.png"]),
        )
        assert connection.execute("SELECT COUNT(*) FROM l3_summary_chunks").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM l4_skill_chunks").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM embedding_rebuild_jobs").fetchone() == (0,)
        assert connection.execute(
            "SELECT episode_id FROM episodes_fts ORDER BY episode_id"
        ).fetchall() == [("episode-roundtrip",)]
        assert connection.execute(
            "SELECT summary_id FROM l3_summaries_fts ORDER BY summary_id"
        ).fetchall() == [("summary-roundtrip",)]
        assert connection.execute(
            "SELECT skill_id FROM l4_skills_fts ORDER BY skill_id"
        ).fetchall() == [("skill-roundtrip",)]

    assert sorted(path.name for path in archive_dir.glob("*.db")) == ["2026-08-01.db"]
    with sqlite3.connect(archive_path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert connection.execute(
            "SELECT event_id, payload_json FROM archived_l1_events"
        ).fetchall() == [("archive-event-roundtrip", json.dumps({"marker": "roundtrip"}))]
        assert connection.execute(
            "SELECT summary_id, payload_json FROM archived_l3_summaries"
        ).fetchall() == [("archive-summary-roundtrip", json.dumps({"marker": "roundtrip"}))]
    assert (archive_dir / "README.txt").read_text(encoding="utf-8") == ("unmanaged archive note")
    assert asset_path.read_bytes() == asset_bytes
    assert [
        path.relative_to(paths.manual_entry_assets_dir).as_posix()
        for path in paths.manual_entry_assets_dir.rglob("*")
        if path.is_file()
    ] == [f"{asset_path.stem[:2]}/{asset_path.name}"]

    return (
        tuple(l1_rows),
        tuple(l0_state or ()),
        tuple(sorted(counts.items())),
        asset_path.read_bytes(),
        archive_path.read_bytes(),
    )


async def _inspect_mutate_and_restore(
    *,
    paths: RuntimePaths,
    archive_dir: Path,
    backup_path: Path,
    attempt: int,
) -> tuple[dict[str, int], Path]:
    inspection = inspect_memory_backup(
        source_path=backup_path,
        password=None,
        runtime_paths=paths,
        archive_target=archive_dir,
    )
    _mutate_live_memory(paths, archive_dir, attempt=attempt)
    candidate_root, metadata, manifest = load_restore_candidate(
        runtime_paths=paths,
        candidate_id=str(inspection.candidate_id),
        fingerprint=inspection.fingerprint,
    )
    candidate = ValidatedRestoreCandidate.from_preflight(
        candidate_root=candidate_root,
        metadata=metadata,
        manifest=manifest,
    )
    transaction = await prepare_memory_restore(
        candidate=candidate,
        runtime_paths=paths,
        operation_id=f"00000000-0000-4000-8000-{attempt:012d}",
    )
    safety_backup_path = transaction.safety_backup_path
    transaction.cutover()
    transaction.commit()
    transaction.finalize_commit()
    delete_restore_candidate(
        runtime_paths=paths,
        candidate_id=str(inspection.candidate_id),
    )
    assert safety_backup_path.is_file()
    return dict(manifest.counts), safety_backup_path


@pytest.mark.asyncio
async def test_complete_memory_backup_restore_roundtrip_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolated_home = tmp_path / "home"
    isolated_home.mkdir(mode=0o700)
    monkeypatch.setenv("HOME", str(isolated_home))
    paths = RuntimePaths(isolated_home / ".magi")
    _migrate_memory_databases(paths)
    archive_dir = paths.memory_dir / "archive"
    archive_dir.mkdir(mode=0o700)
    asset_path, asset_bytes = _seed_complete_memory(paths, archive_dir)

    checkpointed_memory = _CheckpointedMemory()
    snapshot = await create_memory_snapshot(
        runtime_paths=paths,
        archive_dir=archive_dir,
        unified_memory=checkpointed_memory,
        include_l0=True,
    )
    output_directory = tmp_path / "backup-output"
    output_directory.mkdir(mode=0o700)
    try:
        backup_path, backup_manifest = build_memory_backup(
            snapshot=snapshot,
            output_directory=output_directory,
            encryption="none",
            password=None,
        )
    finally:
        discard_snapshot(snapshot)
    assert checkpointed_memory.checkpoints == 1
    assert backup_manifest.counts["manual_entry_assets"] == 1
    assert {record.path: record.record_count for record in backup_manifest.files}[
        "archives/2026-08-01.db"
    ] == 2

    first_counts, first_safety_backup = await _inspect_mutate_and_restore(
        paths=paths,
        archive_dir=archive_dir,
        backup_path=backup_path,
        attempt=1,
    )
    assert first_counts == backup_manifest.counts
    first_state = _assert_complete_restored_state(
        paths,
        archive_dir,
        expected_counts=first_counts,
        asset_path=asset_path,
        asset_bytes=asset_bytes,
    )

    second_counts, second_safety_backup = await _inspect_mutate_and_restore(
        paths=paths,
        archive_dir=archive_dir,
        backup_path=backup_path,
        attempt=2,
    )
    assert second_counts == first_counts
    second_state = _assert_complete_restored_state(
        paths,
        archive_dir,
        expected_counts=second_counts,
        asset_path=asset_path,
        asset_bytes=asset_bytes,
    )

    assert second_state == first_state
    assert first_safety_backup != second_safety_backup
    assert first_safety_backup.is_file()
    assert second_safety_backup.is_file()
