from __future__ import annotations

from contextlib import asynccontextmanager
import errno
import json
from pathlib import Path
import sqlite3
import zipfile

import pytest

from magi.db.runner import MIGRATION_TARGETS, run_upgrade_head
from magi.memory.portability import export as export_module
from magi.memory.portability.errors import MemoryPortabilityError
from magi.memory.portability.export import build_readable_export
from magi.memory.portability.storage import create_memory_snapshot, discard_snapshot
from magi.utils.runtime import RuntimePaths


class _FakeL0:
    async def checkpoint_all(self) -> None:
        return None


class _FakeUnifiedMemory:
    def __init__(self) -> None:
        self.l0 = _FakeL0()

    @asynccontextmanager
    async def memory_maintenance_guard(self):
        yield


def _migrate_memory_databases(paths: RuntimePaths) -> None:
    selected = tuple(
        target for target in MIGRATION_TARGETS if target.name in {"l1", "memory_shared"}
    )
    run_upgrade_head(paths, targets=selected)


def _seed_public_memory_contract(paths: RuntimePaths) -> None:
    with sqlite3.connect(paths.l1_memory_db_path) as connection:
        connection.execute(
            """
            INSERT INTO fact_events(
                event_id, timestamp, created_at, event_type, source, source_item_id,
                memory_domain, cognition_eligible, retention_class, session_id,
                turn_id, session_seq, user_id, content, author_type, content_type,
                importance_score, evidence_status, evidence_class,
                evidence_rule_version, l1_retrieval_scope
            ) VALUES (
                'event-1', 10, 11, 'manual_entry', 'manual_entry', 'entry-1',
                1, 1, 3, 'session-1', 'turn-1', 1, 'user-1', 'hello memory',
                1, 1, 0.8, 2, 2, 6, 2
            )
            """
        )
        connection.execute(
            """
            INSERT INTO l1_event_payload(event_id, content, created_at)
            VALUES ('event-1', 'full source text', 11)
            """
        )
        connection.execute("ALTER TABLE fact_events ADD COLUMN future_internal_secret TEXT")
        connection.execute("UPDATE fact_events SET future_internal_secret = 'l1-storage-secret'")
        connection.commit()

    with sqlite3.connect(paths.memory_db_path) as connection:
        connection.execute(
            """
            INSERT INTO l0_sessions(
                session_id, user_id, status, started_at, last_active_at, metadata
            ) VALUES ('session-1', 'user-1', 'active', 1, 2, '{}')
            """
        )
        connection.execute(
            """
            INSERT INTO l0_attention_items(
                item_id, session_id, kind, summary, status, salience, confidence,
                evidence_mode, source_turn_ids, source_event_ids, first_seen_at,
                last_reinforced_at, metadata
            ) VALUES (
                'attention-1', 'session-1', 'topic', 'remember the export',
                'active', 0.9, 0.8, 'explicit', '["turn-1"]', '["event-1"]',
                1, 2, '{}'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO entity_catalog(
                entity_id, canonical_name, entity_type, created_at, updated_at
            ) VALUES ('entity-1', 'Alice', 'person', 12, 13)
            """
        )
        connection.execute(
            """
            INSERT INTO entity_aliases(
                entity_id, alias_text, normalized_alias, confidence,
                created_at, updated_at, is_independent
            ) VALUES ('entity-1', 'Al', 'al', 0.9, 13, 14, 0)
            """
        )
        connection.execute(
            """
            INSERT INTO entity_mentions(
                mention_text, normalized_surface, entity_type,
                evidence_event_ids, evidence_text, resolved_entity_id,
                confidence, created_at
            ) VALUES (
                'Alice', 'alice', 'person', '["event-1"]',
                'Alice wrote the memory', 'entity-1', 0.95, 14
            )
            """
        )
        connection.execute(
            """
            INSERT INTO entity_name_evidence(
                entity_id, name_kind, normalized_name, display_name,
                event_id, confidence, created_at, updated_at
            ) VALUES (
                'entity-1', 'alias', 'al', 'Al', 'event-1', 0.9, 14, 14
            )
            """
        )
        connection.execute(
            """
            INSERT INTO l2_grounded_claims(
                claim_id, identity_key, extractor_contract_version,
                evidence_rule_version, origin_attempt_key, user_id,
                subject_ref, subject_type, canonical_predicate, fact_kind,
                object_type, polarity, specificity, confidence,
                object_value_json, object_surface, temporal_cue,
                availability, created_at, updated_at
            ) VALUES (
                'claim-1', 'claim-identity-1', 1, 6, 'attempt-1', 'user-1',
                'entity-1', 'person', 'LIKES', 'preference', 'text',
                'positive', 'specific', 0.9, '"tea"', 'tea', 'current',
                'active', 15, 16
            )
            """
        )
        connection.execute(
            """
            INSERT INTO l2_claim_evidence(
                claim_id, event_id, link_role, required_for_grounding,
                event_time, timestamp_confidence, timestamp_quality,
                timestamp_anchor_source, evidence_rule_version, evidence_mode,
                source_type, source_domain, author_type, evidence_class,
                evidence_locator_json, created_at
            ) VALUES (
                'claim-1', 'event-1', 'supporting', 1, 10, 'high', 'exact',
                'event', 6, 'direct', 'manual_entry', 'personal', 'user',
                'user_self_report', '{"event_id":"event-1"}', 16
            )
            """
        )
        connection.execute(
            """
            INSERT INTO l2_claim_entity_refs(
                claim_id, ref_role, entity_id, resolution_version, created_at
            ) VALUES ('claim-1', 'subject', 'entity-1', 1, 16)
            """
        )
        connection.execute(
            """
            INSERT INTO location_samples(
                sample_id, source, sampled_at, lat, lng, accuracy_m,
                city, region, country, metadata_json, created_at
            ) VALUES (
                'sample-1', 'manual_entry', 17, 30.2741, 120.1551, 8,
                'Hangzhou', 'Zhejiang', 'CN', '{"event_id":"event-1"}', 17
            )
            """
        )
        connection.execute(
            """
            INSERT INTO place_labels(
                label_id, center_lat, center_lng, radius_m, user_label, created_at
            ) VALUES ('place-1', 30.2741, 120.1551, 100, 'Home', 17)
            """
        )
        connection.execute(
            """
            INSERT INTO experiences(
                experience_id, status, title, time_start, time_end,
                experience_type, intent, outcome, magi_interpretation,
                narrative_score, primary_entity_ids, primary_place_ids,
                primary_topic_keys, source_episode_count, source_event_count,
                created_at, updated_at, source_seed_id
            ) VALUES (
                'experience-1', 'confirmed', 'Tea at home', 10, 20,
                'moment', 'relax', 'rested', 'A quiet break', 0.8,
                '["entity-1"]', '["place-1"]', '["tea"]', 0, 1,
                18, 19, 'seed-1'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO experience_members(
                experience_id, member_type, member_id, role, confidence, added_at
            ) VALUES ('experience-1', 'event', 'event-1', 'core', 0.95, 19)
            """
        )
        connection.execute(
            """
            INSERT INTO experience_key_events(
                experience_id, event_id, role, reason, confidence, added_at
            ) VALUES (
                'experience-1', 'event-1', 'turning_point',
                'Primary source event', 0.95, 19
            )
            """
        )
        connection.execute(
            """
            INSERT INTO experience_seeds(
                seed_id, seed_type, status, title, description,
                anchor_entity_ids, anchor_place_ids, anchor_topic_keys,
                time_start, time_end, confidence, created_by,
                source_ref_type, source_ref_id, promoted_experience_id,
                created_at, updated_at, last_evaluated_at
            ) VALUES (
                'seed-1', 'event_cluster', 'promoted', 'Tea break seed',
                'A candidate experience', '["entity-1"]', '["place-1"]',
                '["tea"]', 10, 20, 0.85, 'system', 'event', 'event-1',
                'experience-1', 17, 19, 19
            )
            """
        )
        connection.execute(
            """
            INSERT INTO experience_seed_evidence(
                seed_id, ref_type, ref_id, role, confidence, reason, created_at
            ) VALUES (
                'seed-1', 'event', 'event-1', 'support', 0.95,
                'Anchor event', 18
            )
            """
        )
        connection.execute(
            """
            INSERT INTO experience_chapters(
                experience_id, chapter_id, position, title, summary,
                time_start, time_end, episode_ids_json, event_ids_json,
                created_at, updated_at
            ) VALUES (
                'experience-1', 'chapter-1', 1, 'Tea', 'A quiet tea break',
                10, 20, '[]', '["event-1"]', 19, 19
            )
            """
        )
        connection.execute(
            """
            INSERT INTO user_profile_projection(
                user_id, entity_id, display_name, preferred_form_of_address,
                real_name, birth_date, birth_year, age_years, age_as_of,
                home_location, communication_json, identity_json,
                preferences_json, state_json, field_sources_json,
                field_conflicts_json, completeness_score, refreshed_at,
                created_at, updated_at
            ) VALUES (
                'user-1', 'entity-1', 'Alice', 'Alice', 'Alice Example',
                '1990-01-01', 1990, 36, '2026-08-18', 'Hangzhou',
                '{"tone":"concise"}', '{"birth_date":"1990-01-01"}',
                '{"drink":"tea"}', '{"mood":"calm"}',
                '{"display_name":{"event_id":"event-1"}}', '{}',
                0.9, 20, 20, 20
            )
            """
        )
        connection.execute(
            """
            INSERT INTO summaries(
                summary_id, summary_type, summary_category, period_start,
                period_end, content, source_event_ids, source_event_count,
                created_at, updated_at, derivation_state
            ) VALUES (
                'summary-1', 'daily', 'reflection', 10, 20, 'A stable summary',
                '["event-1"]', 1, 21, 22, 'current'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO procedural_skills(
                skill_id, skill_name, skill_category, skill_type,
                source_event_ids, created_at, updated_at
            ) VALUES (
                'procedure-1', 'Write a changelog', 'writing', 'procedure',
                '["event-1"]', 30, 31
            )
            """
        )
        connection.execute(
            """
            INSERT INTO memory_corrections(
                correction_id, request_id, actor_id, target_kind, target_id,
                slot_key, claim_fingerprint, correction_kind, reason, before_json,
                replacement_json, effective_at, scope_json, source_event_id,
                audit_event_id, replacement_target_id, state, created_at
            ) VALUES (
                'correction-1', 'request-1', 'user-1', 'edge',
                'relationship-1', 'slot-1', 'claim-fingerprint-1', 'record_error',
                'user correction', '{"value":"old"}', '{"value":"new"}',
                40, '{}', 'event-1', 'audit-event-1', 'relationship-2',
                'active', 40
            )
            """
        )
        connection.execute(
            """
            INSERT INTO memory_correction_rules(
                rule_id, correction_id, target_kind, rule_kind, slot_key,
                claim_fingerprint, scope_key, effective_from, active, created_at
            ) VALUES (
                'correction-rule-1', 'correction-1', 'edge', 'authoritative_slot',
                'slot-1', 'claim-fingerprint-1', 'scope-1', 40, 1, 40
            )
            """
        )
        connection.execute(
            """
            INSERT INTO memory_correction_evidence_events(
                correction_id, event_id, target_kind, created_at
            ) VALUES ('correction-1', 'event-1', 'edge', 40)
            """
        )
        connection.execute(
            """
            INSERT INTO memory_forget_claim_rules(
                rule_id, target_kind, claim_fingerprint, semantic_fingerprint,
                forget_kind, evidence_fail_closed, created_at
            ) VALUES (
                'forget-rule-1', 'edge', 'claim-fingerprint-1',
                'semantic-fingerprint-1', 'event', 1, 50
            )
            """
        )
        connection.execute(
            """
            INSERT INTO memory_forget_evidence_events(rule_id, event_id, created_at)
            VALUES ('forget-rule-1', 'event-1', 50)
            """
        )
        connection.execute(
            """
            INSERT INTO memory_correction_forget_barriers(
                correction_id, rule_id, created_at
            ) VALUES ('correction-1', 'forget-rule-1', 50)
            """
        )
        connection.execute(
            """
            INSERT INTO memory_source_event_tombstones(event_id, reason, created_at)
            VALUES ('forgotten-event-1', 'user_request', 50)
            """
        )
        for table in (
            "entity_catalog",
            "entity_aliases",
            "entity_mentions",
            "l2_claim_entity_refs",
            "location_samples",
            "place_labels",
            "experience_members",
            "experience_seeds",
            "experience_seed_evidence",
            "experience_chapters",
            "user_profile_projection",
            "summaries",
            "procedural_skills",
            "memory_corrections",
        ):
            connection.execute(f'ALTER TABLE "{table}" ADD COLUMN future_internal_secret TEXT')
            connection.execute(
                f'UPDATE "{table}" SET future_internal_secret = ?',
                (f"{table}-storage-secret",),
            )
        connection.commit()


def _seed_archive(archive_dir: Path) -> None:
    archive_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(archive_dir / "2026-08-18.db") as connection:
        connection.execute(
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
            )
            """
        )
        connection.execute(
            """
            INSERT INTO archived_l1_events(
                event_id, archived_date, archived_at, event_timestamp,
                event_type, source, session_id, user_id, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "archived-event-1",
                "2026-08-18",
                100,
                90,
                "observation",
                "sensor",
                None,
                "user-1",
                json.dumps(
                    {
                        "content": "archived public content",
                        "evidence_class": "external_observation",
                        "future_internal_secret": "archive-payload-secret",
                    }
                ),
            ),
        )
        connection.commit()


def _jsonl_records(archive: zipfile.ZipFile, path: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in archive.read(path).splitlines()]


@pytest.mark.asyncio
async def test_readable_export_is_a_fixed_versioned_public_dto_contract(
    tmp_path: Path,
) -> None:
    paths = RuntimePaths(tmp_path / "runtime")
    _migrate_memory_databases(paths)
    _seed_public_memory_contract(paths)
    archive_dir = paths.memory_dir / "archive"
    _seed_archive(archive_dir)
    snapshot = await create_memory_snapshot(
        runtime_paths=paths,
        archive_dir=archive_dir,
        unified_memory=_FakeUnifiedMemory(),
        include_l0=True,
    )
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    try:
        output_path, manifest = build_readable_export(
            snapshot=snapshot,
            output_directory=output_dir,
            include_l0=True,
        )
        assert manifest["restorable"] is False
        assert manifest["record_contract"] == {
            "contract_version": 1,
            "encoding": "UTF-8 JSON Lines",
            "record_type_field": "record_type",
            "schema_version_field": "schema_version",
            "layer_field": "layer",
            "timestamps": (
                "Numeric timestamp fields use Unix seconds; calendar date fields use "
                "ISO 8601 strings"
            ),
            "additional_fields": False,
        }

        with zipfile.ZipFile(output_path) as archive:
            schema = json.loads(archive.read("schema.json"))
            stored_manifest = json.loads(archive.read("manifest.json"))
            assert schema == stored_manifest["files"] == manifest["files"]
            populated_reference_paths = {
                "l2/entity_aliases.jsonl",
                "l2/entity_mentions.jsonl",
                "l2/entity_name_evidence.jsonl",
                "l2/claims.jsonl",
                "l2/claim_evidence.jsonl",
                "l2/claim_entity_refs.jsonl",
                "l2/location_samples.jsonl",
                "l2/place_labels.jsonl",
                "l2/experiences.jsonl",
                "l2/experience_members.jsonl",
                "l2/experience_evidence.jsonl",
                "l2/experience_seeds.jsonl",
                "l2/experience_seed_evidence.jsonl",
                "l2/experience_chapters.jsonl",
                "l3/user_profiles.jsonl",
            }
            assert {
                "l0/attention_items.jsonl",
                "l1/events.jsonl",
                "l2/entities.jsonl",
                "l3/summaries.jsonl",
                "l4/procedures.jsonl",
                "governance/corrections.jsonl",
                "governance/forget_rules.jsonl",
                "archives/2026-08-18/l1_events.jsonl",
                "archives/2026-08-18/l3_summaries.jsonl",
                *populated_reference_paths,
            } <= set(schema)
            assert all(schema[path]["record_count"] == 1 for path in populated_reference_paths)

            for path, contract in schema.items():
                expected_fields = {field["name"] for field in contract["fields"]}
                for record in _jsonl_records(archive, path):
                    assert set(record) == expected_fields
                    assert record["record_type"] == contract["record_type"]
                    assert record["schema_version"] == contract["schema_version"] == 1
                    assert record["layer"] == contract["layer"]

            event = _jsonl_records(archive, "l1/events.jsonl")[0]
            assert event["memory_domain"] == "user_authored"
            assert event["retention_class"] == "permanent"
            assert event["author_type"] == "user"
            assert event["evidence_class"] == "user_self_report"
            assert event["retrieval_scope"] == "fact_authoritative"
            assert event["status"] == "active"

            entity = _jsonl_records(archive, "l2/entities.jsonl")[0]
            assert entity["display_name"] == "Alice"
            alias = _jsonl_records(archive, "l2/entity_aliases.jsonl")[0]
            mention = _jsonl_records(archive, "l2/entity_mentions.jsonl")[0]
            name_evidence = _jsonl_records(archive, "l2/entity_name_evidence.jsonl")[0]
            claim = _jsonl_records(archive, "l2/claims.jsonl")[0]
            claim_evidence = _jsonl_records(archive, "l2/claim_evidence.jsonl")[0]
            claim_ref = _jsonl_records(archive, "l2/claim_entity_refs.jsonl")[0]
            location = _jsonl_records(archive, "l2/location_samples.jsonl")[0]
            place = _jsonl_records(archive, "l2/place_labels.jsonl")[0]
            experience = _jsonl_records(archive, "l2/experiences.jsonl")[0]
            experience_member = _jsonl_records(archive, "l2/experience_members.jsonl")[0]
            experience_evidence = _jsonl_records(archive, "l2/experience_evidence.jsonl")[0]
            seed = _jsonl_records(archive, "l2/experience_seeds.jsonl")[0]
            seed_evidence = _jsonl_records(archive, "l2/experience_seed_evidence.jsonl")[0]
            chapter = _jsonl_records(archive, "l2/experience_chapters.jsonl")[0]
            profile = _jsonl_records(archive, "l3/user_profiles.jsonl")[0]

            assert alias["entity_id"] == mention["resolved_entity_id"] == entity["entity_id"]
            assert mention["source_event_ids"] == [event["event_id"]]
            assert name_evidence["entity_id"] == alias["entity_id"]
            assert name_evidence["source_event_id"] == event["event_id"]
            assert claim_evidence["claim_id"] == claim["claim_id"]
            assert claim_evidence["source_event_id"] == event["event_id"]
            assert claim_ref == {
                "record_type": "l2_claim_entity_ref",
                "schema_version": 1,
                "layer": "L2",
                "claim_id": claim["claim_id"],
                "category": "subject",
                "entity_id": entity["entity_id"],
                "resolution_version": 1,
                "status": "active",
                "created_at": 16.0,
                "invalidated_at": None,
                "invalidated_reason": None,
            }
            assert location["metadata"] == {"event_id": event["event_id"]}
            assert place["place_label_id"] in experience["primary_place_ids"]
            assert experience_member["experience_id"] == experience["experience_id"]
            assert experience_member["member_id"] == event["event_id"]
            assert experience_evidence["experience_id"] == experience["experience_id"]
            assert experience_evidence["source_event_id"] == event["event_id"]
            assert seed["promoted_experience_id"] == experience["experience_id"]
            assert experience["source_seed_id"] == seed["seed_id"]
            assert seed["anchor_entity_ids"] == [entity["entity_id"]]
            assert seed["anchor_place_ids"] == [place["place_label_id"]]
            assert seed_evidence["seed_id"] == seed["seed_id"]
            assert seed_evidence["reference_id"] == event["event_id"]
            assert chapter["experience_id"] == experience["experience_id"]
            assert chapter["source_event_ids"] == [event["event_id"]]
            assert profile["entity_id"] == entity["entity_id"]
            assert profile["field_sources"] == {"display_name": {"event_id": event["event_id"]}}
            assert _jsonl_records(archive, "l3/summaries.jsonl")[0]["source_event_ids"] == [
                "event-1"
            ]
            assert _jsonl_records(archive, "l4/procedures.jsonl")[0]["source_event_ids"] == [
                "event-1"
            ]
            correction = _jsonl_records(archive, "governance/corrections.jsonl")[0]
            assert correction["replacement_target_id"] == "relationship-2"
            assert correction["replacement"] == {"value": "new"}
            forget_rule = _jsonl_records(archive, "governance/forget_rules.jsonl")[0]
            assert forget_rule["semantic_fingerprint"] == "semantic-fingerprint-1"
            correction_forget = _jsonl_records(archive, "governance/correction_forget_links.jsonl")[
                0
            ]
            assert correction_forget["correction_id"] == "correction-1"
            assert correction_forget["forget_rule_id"] == "forget-rule-1"
            archived = _jsonl_records(archive, "archives/2026-08-18/l1_events.jsonl")[0]
            assert archived["content"] == "archived public content"
            assert archived["status"] == "archived"
            assert _jsonl_records(archive, "archives/2026-08-18/l3_summaries.jsonl") == []

            readme = archive.read("README.txt").decode("utf-8")
            assert "This export cannot be restored into Magi." in readme
            for path, contract in schema.items():
                field_names = ", ".join(field["name"] for field in contract["fields"])
                assert f"- {path} ({contract['record_type']} v1): {field_names}" in readme

            exported_text = b"\n".join(
                archive.read(path) for path in archive.namelist() if not path.startswith("assets/")
            )
            for forbidden in (
                b"future_internal_secret",
                b"-storage-secret",
                b"l1-storage-secret",
                b"entity_catalog-storage-secret",
                b"summaries-storage-secret",
                b"procedural_skills-storage-secret",
                b"memory_corrections-storage-secret",
                b"archive-payload-secret",
                b"history_import_jobs",
                b"embedding_rebuild_jobs",
            ):
                assert forbidden not in exported_text
    finally:
        discard_snapshot(snapshot)


@pytest.mark.asyncio
async def test_readable_export_omits_runtime_l0_unless_requested(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path / "runtime")
    _migrate_memory_databases(paths)
    _seed_public_memory_contract(paths)
    snapshot = await create_memory_snapshot(
        runtime_paths=paths,
        archive_dir=paths.memory_dir / "archive",
        unified_memory=_FakeUnifiedMemory(),
        include_l0=True,
    )
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    try:
        output_path, manifest = build_readable_export(
            snapshot=snapshot,
            output_directory=output_dir,
            include_l0=False,
        )
        assert manifest["includes_l0"] is False
        with zipfile.ZipFile(output_path) as archive:
            schema = json.loads(archive.read("schema.json"))
            assert not any(path.startswith("l0/") for path in schema)
            assert "governance/l0_forgotten_source_refs.jsonl" in schema
            assert "L0 short-term attention is omitted by default" in archive.read(
                "README.txt"
            ).decode("utf-8")
    finally:
        discard_snapshot(snapshot)


@pytest.mark.asyncio
async def test_readable_export_reserves_for_json_expansion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = RuntimePaths(tmp_path / "runtime")
    _migrate_memory_databases(paths)
    _seed_public_memory_contract(paths)
    snapshot = await create_memory_snapshot(
        runtime_paths=paths,
        archive_dir=paths.memory_dir / "archive",
        unified_memory=_FakeUnifiedMemory(),
        include_l0=False,
    )
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    checks: list[tuple[Path, int]] = []
    monkeypatch.setattr(
        export_module,
        "_require_free_space",
        lambda directory, required: checks.append((Path(directory), int(required))),
    )
    try:
        structured_bytes = sum(
            Path(item.source_path).stat().st_size
            for item in snapshot.files
            if item.purpose != "manual_entry_asset"
        )
        asset_bytes = sum(
            Path(item.source_path).stat().st_size
            for item in snapshot.files
            if item.purpose == "manual_entry_asset"
        )
        build_readable_export(
            snapshot=snapshot,
            output_directory=output_dir,
            include_l0=False,
        )
        assert checks == [
            (
                output_dir.resolve(),
                structured_bytes * 16 + asset_bytes + 8 * 1024 * 1024,
            )
        ]
        assert checks[0][1] > structured_bytes + asset_bytes
    finally:
        discard_snapshot(snapshot)


@pytest.mark.asyncio
async def test_readable_export_maps_write_enospc_to_insufficient_space(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = RuntimePaths(tmp_path / "runtime")
    _migrate_memory_databases(paths)
    _seed_public_memory_contract(paths)
    snapshot = await create_memory_snapshot(
        runtime_paths=paths,
        archive_dir=paths.memory_dir / "archive",
        unified_memory=_FakeUnifiedMemory(),
        include_l0=False,
    )
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    def fail_to_open(_path: Path):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(export_module, "_open_private_exclusive", fail_to_open)
    try:
        with pytest.raises(MemoryPortabilityError) as caught:
            build_readable_export(
                snapshot=snapshot,
                output_directory=output_dir,
                include_l0=False,
            )
        assert caught.value.code == "insufficient_space"
        assert list(output_dir.iterdir()) == []
    finally:
        discard_snapshot(snapshot)
