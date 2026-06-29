from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest

from magi.memory.store_maintenance import UnifiedMemoryMaintenanceMixin


class _DummyL2:
    def __init__(self, db_path: Path) -> None:
        self.db_path = str(db_path)
        self.initialized = False

    async def initialize(self) -> None:
        self.initialized = True


class _MaintenanceHarness(UnifiedMemoryMaintenanceMixin):
    def __init__(self, l2: _DummyL2, archive_dir: Path) -> None:
        self.l0 = None
        self.l1 = None
        self.l2 = l2
        self.l3 = None
        self.l4 = None
        self._archive_dir = archive_dir


@pytest.mark.asyncio
async def test_l2_referenced_l1_event_ids_collects_active_l2_sources(tmp_path) -> None:
    db_path = tmp_path / "memory.db"
    await _seed_l2_reference_db(db_path)
    l2 = _DummyL2(db_path)
    harness = _MaintenanceHarness(l2, tmp_path / "archive")

    protected = await harness._l2_referenced_l1_event_ids(
        [
            "",
            "episode-active",
            "episode-active",
            "episode-terminal",
            "episode-excluded",
            "experience-event",
            "experience-episode",
            "experience-merged",
            "key-event",
            "key-merged",
            "seed-event",
            "seed-episode",
            "seed-archived",
            "graph-event",
            "graph-archived",
            "assertion-event",
            "assertion-archived",
            "facet-event",
            "facet-archived",
            "unprotected",
        ]
    )

    assert l2.initialized is True
    assert protected == {
        "episode-active",
        "experience-event",
        "experience-episode",
        "key-event",
        "seed-event",
        "seed-episode",
        "graph-event",
        "assertion-event",
        "facet-event",
    }


async def _seed_l2_reference_db(db_path: Path) -> None:
    async with aiosqlite.connect(db_path) as db:
        await _create_l2_reference_tables(db)
        await _insert_episode_refs(db)
        await _insert_experience_refs(db)
        await _insert_seed_refs(db)
        await _insert_json_refs(db)
        await db.commit()


async def _create_l2_reference_tables(db: aiosqlite.Connection) -> None:
    await db.executescript("""
    CREATE TABLE episodes (
        episode_id TEXT PRIMARY KEY,
        status TEXT NOT NULL
    );
    CREATE TABLE episode_events (
        episode_id TEXT NOT NULL,
        event_id TEXT NOT NULL,
        membership_role TEXT NOT NULL
    );
    CREATE TABLE experiences (
        experience_id TEXT PRIMARY KEY,
        status TEXT NOT NULL
    );
    CREATE TABLE experience_members (
        experience_id TEXT NOT NULL,
        member_type TEXT NOT NULL,
        member_id TEXT NOT NULL,
        role TEXT NOT NULL
    );
    CREATE TABLE experience_key_events (
        experience_id TEXT NOT NULL,
        event_id TEXT NOT NULL
    );
    CREATE TABLE experience_seeds (
        seed_id TEXT PRIMARY KEY,
        status TEXT NOT NULL
    );
    CREATE TABLE experience_seed_evidence (
        seed_id TEXT NOT NULL,
        ref_type TEXT NOT NULL,
        ref_id TEXT NOT NULL
    );
    CREATE TABLE knowledge_graph (
        evidence_event_ids TEXT,
        status TEXT NOT NULL
    );
    CREATE TABLE tom_trait_assertions (
        evidence_events TEXT,
        status TEXT NOT NULL
    );
    CREATE TABLE entity_facets (
        evidence_event_ids TEXT,
        status TEXT NOT NULL
    );
    """)


async def _insert_episode_refs(db: aiosqlite.Connection) -> None:
    await db.executemany(
        "INSERT INTO episodes(episode_id, status) VALUES (?, ?)",
        [
            ("ep-active", "active"),
            ("ep-archived", "archived"),
            ("ep-experience", "active"),
            ("ep-seed", "active"),
        ],
    )
    await db.executemany(
        "INSERT INTO episode_events(episode_id, event_id, membership_role) VALUES (?, ?, ?)",
        [
            ("ep-active", "episode-active", "member"),
            ("ep-active", "episode-excluded", "excluded"),
            ("ep-archived", "episode-terminal", "member"),
            ("ep-experience", "experience-episode", "member"),
            ("ep-seed", "seed-episode", "member"),
        ],
    )


async def _insert_experience_refs(db: aiosqlite.Connection) -> None:
    await db.executemany(
        "INSERT INTO experiences(experience_id, status) VALUES (?, ?)",
        [("exp-active", "active"), ("exp-merged", "merged")],
    )
    await db.executemany(
        """
        INSERT INTO experience_members(experience_id, member_type, member_id, role)
        VALUES (?, ?, ?, ?)
        """,
        [
            ("exp-active", "event", "experience-event", "member"),
            ("exp-active", "episode", "ep-experience", "member"),
            ("exp-active", "event", "experience-excluded", "excluded"),
            ("exp-merged", "event", "experience-merged", "member"),
        ],
    )
    await db.executemany(
        "INSERT INTO experience_key_events(experience_id, event_id) VALUES (?, ?)",
        [("exp-active", "key-event"), ("exp-merged", "key-merged")],
    )


async def _insert_seed_refs(db: aiosqlite.Connection) -> None:
    await db.executemany(
        "INSERT INTO experience_seeds(seed_id, status) VALUES (?, ?)",
        [
            ("seed-active", "candidate"),
            ("seed-accepted", "accepted"),
            ("seed-old", "archived"),
        ],
    )
    await db.executemany(
        """
        INSERT INTO experience_seed_evidence(seed_id, ref_type, ref_id)
        VALUES (?, ?, ?)
        """,
        [
            ("seed-active", "event", "seed-event"),
            ("seed-accepted", "episode", "ep-seed"),
            ("seed-old", "event", "seed-archived"),
        ],
    )


async def _insert_json_refs(db: aiosqlite.Connection) -> None:
    await db.executemany(
        "INSERT INTO knowledge_graph(evidence_event_ids, status) VALUES (?, ?)",
        [('["graph-event"]', "active"), ('["graph-archived"]', "archived")],
    )
    await db.executemany(
        "INSERT INTO tom_trait_assertions(evidence_events, status) VALUES (?, ?)",
        [('["assertion-event"]', "active"), ('["assertion-archived"]', "archived")],
    )
    await db.executemany(
        "INSERT INTO entity_facets(evidence_event_ids, status) VALUES (?, ?)",
        [('["facet-event"]', "active"), ('["facet-archived"]', "archived")],
    )
