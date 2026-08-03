"""Tests for revision-fenced L2 entity links in the L1 store."""

from __future__ import annotations

import math
import sqlite3

import pytest
from alembic import command

from magi.db.runner import MIGRATION_TARGETS, _build_config
from magi.memory.l1.event_store import L1EventStore


def test_l1_v2_migration_discards_unowned_legacy_projection_rows(tmp_path) -> None:
    db_path = tmp_path / "legacy-l1.db"
    target = next(item for item in MIGRATION_TARGETS if item.name == "l1")
    config = _build_config(target, db_path)
    command.upgrade(config, "v1")
    with sqlite3.connect(db_path) as db:
        db.execute("""
            INSERT INTO l1_event_entities(
                event_id, entity_id, entity_type, confidence, created_at
            ) VALUES ('evt-legacy', 'entity:stale', 'topic', 0.9, 1.0)
            """)
        db.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM l1_event_entities").fetchone() == (0,)
        assert db.execute("SELECT COUNT(*) FROM l1_effective_event_entities").fetchone() == (0,)


@pytest.mark.asyncio
async def test_manual_and_projected_links_share_all_entity_queries(tmp_path) -> None:
    store = L1EventStore(db_path=str(tmp_path / "l1.db"), vector_enabled=False)
    await store.initialize(start_workers=False)

    assert (
        await store.write_event_entities(
            [
                ("evt-a", "entity:manual", "topic", 0.8),
                ("evt-a", "entity:shared", "topic", 0.7),
                ("evt-b", "entity:projected", "topic", 0.6),
            ]
        )
        == 3
    )
    assert await store.replace_projected_event_entities(
        event_id="evt-a",
        revision=1,
        lease_token="lease-1",
        attempt_count=1,
        clear_generation=0,
        mappings=[
            ("entity:projected", "topic", 0.95),
            ("entity:shared", "topic", 0.9),
        ],
    )

    event_links = await store.get_event_entity_ids(["evt-a"])
    assert set(event_links["evt-a"]) == {
        "entity:manual",
        "entity:projected",
        "entity:shared",
    }
    assert event_links["evt-a"].count("entity:shared") == 1
    assert set(await store.resolve_event_entities(["evt-a"])) == set(event_links["evt-a"])
    projected_events = await store.get_entity_event_ids(["entity:projected"])
    assert "evt-a" in projected_events["entity:projected"]
    assert "evt-b" in await store.expand_by_entities(["evt-a"])
    assert ("evt-a", 1) in await store.find_events_by_entities(["entity:projected"])


@pytest.mark.asyncio
async def test_empty_projection_replay_preserves_manual_links_and_satisfies_old_revision(
    tmp_path,
) -> None:
    store = L1EventStore(db_path=str(tmp_path / "l1.db"), vector_enabled=False)
    await store.initialize(start_workers=False)
    await store.write_event_entities(
        [
            ("evt-a", "entity:manual", "topic", 0.8),
            ("evt-a", "entity:shared", "topic", 0.7),
        ]
    )
    assert await store.replace_projected_event_entities(
        event_id="evt-a",
        revision=1,
        lease_token="lease-1",
        attempt_count=1,
        clear_generation=0,
        mappings=[
            ("entity:old", "topic", 0.9),
            ("entity:shared", "topic", 0.9),
        ],
    )
    assert await store.replace_projected_event_entities(
        event_id="evt-a",
        revision=2,
        lease_token="lease-2",
        attempt_count=1,
        clear_generation=0,
        mappings=[],
    )

    assert set((await store.get_event_entity_ids(["evt-a"]))["evt-a"]) == {
        "entity:manual",
        "entity:shared",
    }
    assert await store.replace_projected_event_entities(
        event_id="evt-a",
        revision=1,
        lease_token="lease-1",
        attempt_count=1,
        clear_generation=0,
        mappings=[("entity:stale", "topic", 1.0)],
    )
    assert "entity:stale" not in (await store.get_event_entity_ids(["evt-a"]))["evt-a"]


@pytest.mark.asyncio
async def test_same_revision_requires_identical_canonical_payload(tmp_path) -> None:
    store = L1EventStore(db_path=str(tmp_path / "l1.db"), vector_enabled=False)
    await store.initialize(start_workers=False)
    original = [
        ("entity:b", "topic", 0.8),
        ("entity:a", "person", 0.9),
    ]
    assert await store.replace_projected_event_entities(
        event_id="evt-a",
        revision=1,
        lease_token="lease-1",
        attempt_count=1,
        clear_generation=0,
        mappings=original,
    )
    assert await store.replace_projected_event_entities(
        event_id="evt-a",
        revision=1,
        lease_token="lease-1",
        attempt_count=1,
        clear_generation=0,
        mappings=list(reversed(original)),
    )

    with pytest.raises(RuntimeError, match="conflicting projection payloads"):
        await store.replace_projected_event_entities(
            event_id="evt-a",
            revision=1,
            lease_token="lease-1",
            attempt_count=1,
            clear_generation=0,
            mappings=[("entity:other", "topic", 0.7)],
        )

    assert set((await store.get_event_entity_ids(["evt-a"]))["evt-a"]) == {
        "entity:a",
        "entity:b",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "confidence",
    [math.nan, math.inf, -math.inf, -0.01, 1.01],
)
async def test_projection_rejects_non_canonical_confidence(tmp_path, confidence) -> None:
    store = L1EventStore(db_path=str(tmp_path / "l1.db"), vector_enabled=False)
    await store.initialize(start_workers=False)

    with pytest.raises(ValueError, match="confidence"):
        await store.replace_projected_event_entities(
            event_id="evt-invalid",
            revision=1,
            lease_token="lease-1",
            attempt_count=1,
            clear_generation=0,
            mappings=[("entity:a", "topic", confidence)],
        )

    assert (await store.get_event_entity_ids(["evt-invalid"]))["evt-invalid"] == []


@pytest.mark.asyncio
async def test_multi_event_conflict_rolls_back_whole_batch_then_retry_succeeds(
    tmp_path,
) -> None:
    store = L1EventStore(db_path=str(tmp_path / "l1.db"), vector_enabled=False)
    await store.initialize(start_workers=False)
    assert await store.replace_projected_event_entities(
        event_id="evt-b",
        revision=1,
        lease_token="lease-b1",
        attempt_count=1,
        clear_generation=0,
        mappings=[("entity:b-old", "topic", 0.6)],
    )

    with pytest.raises(RuntimeError, match="conflicting projection payloads"):
        await store.replace_projected_event_entities_batch(
            projections=[
                (
                    "evt-a",
                    1,
                    "lease-a1",
                    1,
                    0,
                    [("entity:a-new", "topic", 0.9)],
                ),
                (
                    "evt-b",
                    1,
                    "lease-b1",
                    1,
                    0,
                    [("entity:b-conflict", "topic", 0.9)],
                ),
            ]
        )

    links = await store.get_event_entity_ids(["evt-a", "evt-b"])
    assert links["evt-a"] == []
    assert links["evt-b"] == ["entity:b-old"]

    assert await store.replace_projected_event_entities_batch(
        projections=[
            (
                "evt-a",
                1,
                "lease-a1",
                1,
                0,
                [("entity:a-new", "topic", 0.9)],
            ),
            (
                "evt-b",
                2,
                "lease-b2",
                2,
                0,
                [("entity:b-new", "topic", 0.9)],
            ),
        ]
    )
    links = await store.get_event_entity_ids(["evt-a", "evt-b"])
    assert links["evt-a"] == ["entity:a-new"]
    assert links["evt-b"] == ["entity:b-new"]


@pytest.mark.asyncio
async def test_second_event_storage_fault_rolls_back_first_then_retry_succeeds(
    tmp_path,
) -> None:
    store = L1EventStore(db_path=str(tmp_path / "l1.db"), vector_enabled=False)
    await store.initialize(start_workers=False)
    projections = [
        (
            "evt-a",
            1,
            "lease-batch",
            1,
            0,
            [("entity:a", "topic", 0.8)],
        ),
        (
            "evt-b",
            1,
            "lease-batch",
            1,
            0,
            [("entity:b", "topic", 0.8)],
        ),
    ]
    with sqlite3.connect(store.db_path) as db:
        db.execute(
            """
            CREATE TRIGGER fail_second_projected_event
            BEFORE INSERT ON l1_projected_event_entities
            WHEN NEW.event_id = 'evt-b'
            BEGIN
                SELECT RAISE(ABORT, 'injected second event fault');
            END
            """
        )
        db.commit()

    with pytest.raises(sqlite3.IntegrityError, match="injected second event fault"):
        await store.replace_projected_event_entities_batch(projections=projections)
    assert await store.get_event_entity_ids(["evt-a", "evt-b"]) == {
        "evt-a": [],
        "evt-b": [],
    }

    with sqlite3.connect(store.db_path) as db:
        db.execute("DROP TRIGGER fail_second_projected_event")
        db.commit()
    assert await store.replace_projected_event_entities_batch(projections=projections)
    assert await store.get_event_entity_ids(["evt-a", "evt-b"]) == {
        "evt-a": ["entity:a"],
        "evt-b": ["entity:b"],
    }


@pytest.mark.asyncio
async def test_partially_superseded_batch_applies_remaining_events_serializably(
    tmp_path,
) -> None:
    store = L1EventStore(db_path=str(tmp_path / "l1.db"), vector_enabled=False)
    await store.initialize(start_workers=False)
    assert await store.replace_projected_event_entities(
        event_id="evt-a",
        revision=2,
        lease_token="governance-a2",
        attempt_count=1,
        clear_generation=0,
        mappings=[("entity:a-newer", "topic", 1.0)],
    )

    assert await store.replace_projected_event_entities_batch(
        projections=[
            (
                "evt-a",
                1,
                "lease-batch",
                1,
                0,
                [("entity:a-stale", "topic", 0.5)],
            ),
            (
                "evt-b",
                1,
                "lease-batch",
                1,
                0,
                [("entity:b", "topic", 0.8)],
            ),
        ]
    )

    links = await store.get_event_entity_ids(["evt-a", "evt-b"])
    assert links["evt-a"] == ["entity:a-newer"]
    assert links["evt-b"] == ["entity:b"]


@pytest.mark.asyncio
async def test_direct_l1_clear_refuses_to_orphan_projected_links(tmp_path) -> None:
    store = L1EventStore(db_path=str(tmp_path / "l1.db"), vector_enabled=False)
    await store.initialize(start_workers=False)
    assert await store.replace_projected_event_entities(
        event_id="evt-a",
        revision=1,
        lease_token="lease-1",
        attempt_count=1,
        clear_generation=0,
        mappings=[("entity:a", "topic", 0.9)],
    )

    with pytest.raises(RuntimeError, match="requires unified memory clear"):
        await store.clear(restart_workers=False)
    assert (await store.get_event_entity_ids(["evt-a"]))["evt-a"] == ["entity:a"]

    assert (
        await store.clear(
            restart_workers=False,
            entity_link_clear_generation=1,
        )
        == 0
    )
    assert (await store.get_event_entity_ids(["evt-a"]))["evt-a"] == []
