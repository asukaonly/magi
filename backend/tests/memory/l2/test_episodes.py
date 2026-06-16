"""Tests for P1 episodic memory: store CRUD, formation, consolidation."""

from __future__ import annotations

import time
import uuid

import pytest


@pytest.mark.asyncio
async def test_create_and_get_episode(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    eid = str(uuid.uuid4())
    await store.create_episode(
        episode_id=eid,
        episode_type="activity",
        time_start=1000.0,
        time_end=2000.0,
        primary_entity_ids=["user:alice", "place:office"],
        primary_topic_keys=["coding"],
        source_event_count=5,
    )

    ep = await store.get_episode(episode_id=eid)
    assert ep is not None
    assert ep["episode_id"] == eid
    assert ep["episode_type"] == "activity"
    assert ep["status"] == "candidate"
    assert ep["time_start"] == 1000.0
    assert ep["time_end"] == 2000.0
    assert ep["primary_entity_ids"] == ["user:alice", "place:office"]
    assert ep["primary_topic_keys"] == ["coding"]
    assert ep["source_event_count"] == 5


@pytest.mark.asyncio
async def test_update_episode(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    eid = str(uuid.uuid4())
    await store.create_episode(
        episode_id=eid, time_start=100.0, time_end=200.0,
    )

    ok = await store.update_episode(
        episode_id=eid,
        status="active",
        label="Morning work",
        summary="Coding session in the morning",
        source_event_count=10,
    )
    assert ok is True

    ep = await store.get_episode(episode_id=eid)
    assert ep["status"] == "active"
    assert ep["label"] == "Morning work"
    assert ep["summary"] == "Coding session in the morning"
    assert ep["source_event_count"] == 10


@pytest.mark.asyncio
async def test_update_episode_not_found(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    ok = await store.update_episode(episode_id="nonexistent", status="active")
    assert ok is False


@pytest.mark.asyncio
async def test_list_episodes_with_filters(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    for i in range(5):
        await store.create_episode(
            episode_id=f"ep-{i}",
            episode_type="activity" if i < 3 else "session",
            time_start=float(i * 100),
            time_end=float(i * 100 + 50),
            source_event_count=i + 1,
        )

    # Filter by type
    activities = await store.list_episodes(episode_type="activity")
    assert len(activities) == 3

    sessions = await store.list_episodes(episode_type="session")
    assert len(sessions) == 2

    # Filter by status
    candidates = await store.list_episodes(status="candidate")
    assert len(candidates) == 5

    # Filter by time window
    in_range = await store.list_episodes(time_start=100.0, time_end=250.0)
    assert len(in_range) == 2  # ep-1 and ep-2

    # Limit and offset
    limited = await store.list_episodes(limit=2)
    assert len(limited) == 2


@pytest.mark.asyncio
async def test_count_episodes(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    for i in range(3):
        await store.create_episode(
            episode_id=f"ep-{i}",
            time_start=float(i * 100),
            time_end=float(i * 100 + 50),
        )

    assert await store.count_episodes() == 3
    assert await store.count_episodes(status="candidate") == 3
    assert await store.count_episodes(status="active") == 0


@pytest.mark.asyncio
async def test_episode_events_crud(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    eid = str(uuid.uuid4())
    await store.create_episode(
        episode_id=eid, time_start=100.0, time_end=200.0,
    )

    added = await store.add_episode_events(
        episode_id=eid,
        event_ids=["evt-1", "evt-2", "evt-3"],
        membership_role="member",
    )
    assert added == 3

    events = await store.list_episode_events(episode_id=eid)
    assert len(events) == 3
    assert {e["event_id"] for e in events} == {"evt-1", "evt-2", "evt-3"}

    # Add duplicate — should not fail
    added2 = await store.add_episode_events(
        episode_id=eid,
        event_ids=["evt-2", "evt-4"],
    )
    events_after = await store.list_episode_events(episode_id=eid)
    assert len(events_after) == 4

    # Remove events
    removed = await store.remove_episode_events(
        episode_id=eid, event_ids=["evt-1", "evt-3"]
    )
    assert removed == 2
    remaining = await store.list_episode_events(episode_id=eid)
    assert len(remaining) == 2


@pytest.mark.asyncio
async def test_count_episode_events_dedups_and_matches_membership(l2_store_with_schema):
    """count_episode_events reflects true distinct membership despite re-adds."""
    store = l2_store_with_schema
    await store.create_episode(
        episode_id="a", time_start=1, time_end=2, source_event_count=0
    )
    await store.add_episode_events(episode_id="a", event_ids=["e1", "e2"])
    await store.add_episode_events(
        episode_id="a", event_ids=["e2", "e3"]
    )  # e2 duplicate -> ignored
    assert await store.count_episode_events(episode_id="a") == 3


@pytest.mark.asyncio
async def test_find_episode_for_event(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    eid = str(uuid.uuid4())
    await store.create_episode(
        episode_id=eid, time_start=100.0, time_end=200.0,
    )
    await store.add_episode_events(episode_id=eid, event_ids=["evt-x"])

    found = await store.find_episode_for_event(event_id="evt-x")
    assert found is not None
    assert found["episode_id"] == eid

    not_found = await store.find_episode_for_event(event_id="evt-nonexistent")
    assert not_found is None


@pytest.mark.asyncio
async def test_find_recent_candidate_episode(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    now = time.time()
    # Create a candidate episode ending 10 minutes ago
    eid = str(uuid.uuid4())
    await store.create_episode(
        episode_id=eid,
        time_start=now - 3600,
        time_end=now - 600,
        primary_entity_ids=["user:alice"],
    )

    # Should find it within 30-minute gap
    found = await store.find_recent_candidate_episode(
        max_gap=30 * 60,
        before_time=now,
        entity_ids=["user:alice"],
    )
    assert found is not None
    assert found["episode_id"] == eid

    # Should NOT find it with a 5-minute gap
    not_found = await store.find_recent_candidate_episode(
        max_gap=5 * 60,
        before_time=now,
        entity_ids=["user:alice"],
    )
    assert not_found is None


@pytest.mark.asyncio
async def test_streaming_candidate_formation_creates_new(tmp_path):
    """When no recent candidate exists, a new episode is created."""
    from magi.memory.l2.store import L2CognitionStore
    from magi.memory.l2.episode_formation import assign_events_to_episode
    from magi.memory.l2.models import EpisodeCandidateJob

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    now = time.time()
    jobs = [
        EpisodeCandidateJob(
            event_id="evt-1",
            event_timestamp=now,
            entity_ids=["user:alice"],
            topic_keys=["coding"],
        ),
        EpisodeCandidateJob(
            event_id="evt-2",
            event_timestamp=now + 60,
            entity_ids=["user:alice"],
            topic_keys=["coding"],
        ),
    ]

    episode_id = await assign_events_to_episode(store, jobs)
    assert episode_id is not None

    ep = await store.get_episode(episode_id=episode_id)
    assert ep is not None
    assert ep["status"] == "candidate"
    assert ep["source_event_count"] == 2
    assert "user:alice" in ep["primary_entity_ids"]

    events = await store.list_episode_events(episode_id=episode_id)
    assert len(events) == 2


@pytest.mark.asyncio
async def test_streaming_candidate_formation_extends_existing(tmp_path):
    """When a recent candidate exists and shares theme, it is extended."""
    from magi.memory.l2.store import L2CognitionStore
    from magi.memory.l2.episode_formation import assign_events_to_episode
    from magi.memory.l2.models import EpisodeCandidateJob

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    now = time.time()
    # First batch creates an episode
    first_jobs = [
        EpisodeCandidateJob(
            event_id="evt-1",
            event_timestamp=now,
            entity_ids=["user:alice"],
        ),
    ]
    ep1_id = await assign_events_to_episode(store, first_jobs)

    # Second batch 10 minutes later with same entity
    second_jobs = [
        EpisodeCandidateJob(
            event_id="evt-2",
            event_timestamp=now + 600,
            entity_ids=["user:alice"],
        ),
    ]
    ep2_id = await assign_events_to_episode(store, second_jobs)

    # Should be same episode
    assert ep2_id == ep1_id

    ep = await store.get_episode(episode_id=ep1_id)
    assert ep["source_event_count"] == 2
    assert ep["time_end"] == now + 600


@pytest.mark.asyncio
async def test_extend_path_source_event_count_does_not_drift_on_overlap(tmp_path):
    """Re-including an already-member event must not inflate source_event_count.

    ``episode_events`` has ``INSERT OR IGNORE`` on its PK, so re-adding an
    existing event does NOT grow membership. The stored count must therefore be
    derived from membership (``count_episode_events``), not summed arithmetically
    — otherwise it drifts above the true distinct count (finding #28).
    """
    from magi.memory.l2.store import L2CognitionStore
    from magi.memory.l2.episode_formation import assign_events_to_episode
    from magi.memory.l2.models import EpisodeCandidateJob

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    now = time.time()
    # First batch creates an episode with evt-1, evt-2
    first_jobs = [
        EpisodeCandidateJob(
            event_id="evt-1", event_timestamp=now, entity_ids=["user:alice"]
        ),
        EpisodeCandidateJob(
            event_id="evt-2", event_timestamp=now + 1, entity_ids=["user:alice"]
        ),
    ]
    ep1_id = await assign_events_to_episode(store, first_jobs)

    # Second batch 10 min later lands on the SAME candidate, but re-includes
    # evt-2 (already a member) alongside a fresh evt-3.
    second_jobs = [
        EpisodeCandidateJob(
            event_id="evt-2", event_timestamp=now + 600, entity_ids=["user:alice"]
        ),
        EpisodeCandidateJob(
            event_id="evt-3", event_timestamp=now + 601, entity_ids=["user:alice"]
        ),
    ]
    ep2_id = await assign_events_to_episode(store, second_jobs)
    assert ep2_id == ep1_id  # same candidate extended

    ep = await store.get_episode(episode_id=ep1_id)
    membership = await store.count_episode_events(episode_id=ep1_id)
    # True distinct membership is {evt-1, evt-2, evt-3} == 3.
    assert membership == 3
    # Stored count must equal membership — no drift to 4 (2 + 2 arithmetic).
    assert ep["source_event_count"] == membership == 3


@pytest.mark.asyncio
async def test_streaming_candidate_new_after_gap(tmp_path):
    """When the gap exceeds threshold, a new episode is created."""
    from magi.memory.l2.store import L2CognitionStore
    from magi.memory.l2.episode_formation import assign_events_to_episode
    from magi.memory.l2.models import EpisodeCandidateJob

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    now = time.time()
    # First batch
    first_jobs = [
        EpisodeCandidateJob(
            event_id="evt-1",
            event_timestamp=now,
            entity_ids=["user:alice"],
        ),
    ]
    ep1_id = await assign_events_to_episode(store, first_jobs)

    # Second batch 2 hours later — beyond 30min default gap
    second_jobs = [
        EpisodeCandidateJob(
            event_id="evt-2",
            event_timestamp=now + 7200,
            entity_ids=["user:alice"],
        ),
    ]
    ep2_id = await assign_events_to_episode(store, second_jobs)

    # Should be different episodes
    assert ep2_id != ep1_id


@pytest.mark.asyncio
async def test_formation_honors_episode_type_hint_gap(tmp_path):
    """The episode_type_hint drives the merge gap.

    Two events 20 min apart are split into TWO ``conversation`` episodes
    (conversation gap = 10 min < 20 min) but merged into ONE ``activity``
    episode (activity gap = 30 min > 20 min). This is the value Task 1.2
    unlocks: the extract worker now passes the type hint, so formation
    stops collapsing every kind of event into 30-min activity buckets.
    """
    from magi.memory.l2.store import L2CognitionStore
    from magi.memory.l2.episode_formation import assign_events_to_episode
    from magi.memory.l2.models import EpisodeCandidateJob

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    now = time.time()
    gap = 20 * 60  # 20 minutes

    # conversation hint (10-min gap) → two separate episodes
    conv1 = await assign_events_to_episode(
        store,
        [
            EpisodeCandidateJob(
                event_id="conv-1",
                event_timestamp=now,
                entity_ids=["user:alice"],
                episode_type_hint="conversation",
            ),
        ],
    )
    conv2 = await assign_events_to_episode(
        store,
        [
            EpisodeCandidateJob(
                event_id="conv-2",
                event_timestamp=now + gap,
                entity_ids=["user:alice"],
                episode_type_hint="conversation",
            ),
        ],
    )
    assert conv1 != conv2

    # default activity hint (30-min gap) → same episode, proving the hint
    # (not the timing) is what splits the conversation pair above.
    act1 = await assign_events_to_episode(
        store,
        [
            EpisodeCandidateJob(
                event_id="act-1",
                event_timestamp=now,
                entity_ids=["user:bob"],
                episode_type_hint="activity",
            ),
        ],
    )
    act2 = await assign_events_to_episode(
        store,
        [
            EpisodeCandidateJob(
                event_id="act-2",
                event_timestamp=now + gap,
                entity_ids=["user:bob"],
                episode_type_hint="activity",
            ),
        ],
    )
    assert act1 == act2


@pytest.mark.asyncio
async def test_consolidation_promotes_mature_candidates(tmp_path):
    """Candidates with enough events and age get promoted to active."""
    from magi.memory.l2.store import L2CognitionStore
    from magi.memory.l2.episode_formation import consolidate_episodes

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    now = time.time()
    # Create a candidate with 5 events, created 1 hour ago
    eid = str(uuid.uuid4())
    await store.create_episode(
        episode_id=eid,
        time_start=now - 3600,
        time_end=now - 1800,
        source_event_count=5,
    )
    # Backdate created_at
    from magi.core.sqlite import sqlite_connection_async
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute(
            "UPDATE episodes SET created_at = ? WHERE episode_id = ?",
            (now - 3600, eid),
        )
        await db.commit()

    stats = await consolidate_episodes(store)
    assert stats.promoted == 1

    ep = await store.get_episode(episode_id=eid)
    assert ep["status"] == "active"


@pytest.mark.asyncio
async def test_consolidation_does_not_promote_young(tmp_path):
    """Candidates that are too young should not be promoted."""
    from magi.memory.l2.store import L2CognitionStore
    from magi.memory.l2.episode_formation import consolidate_episodes

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    # Just created — too young
    eid = str(uuid.uuid4())
    await store.create_episode(
        episode_id=eid,
        time_start=time.time(),
        time_end=time.time() + 100,
        source_event_count=10,
    )

    stats = await consolidate_episodes(store)
    assert stats.promoted == 0


@pytest.mark.asyncio
async def test_consolidation_merges_adjacent(tmp_path):
    """Adjacent active episodes of same type with high entity overlap get merged."""
    from magi.memory.l2.store import L2CognitionStore
    from magi.memory.l2.episode_formation import consolidate_episodes

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    now = time.time()
    # Two active episodes 5 minutes apart, same entities
    eid1 = str(uuid.uuid4())
    eid2 = str(uuid.uuid4())
    await store.create_episode(
        episode_id=eid1,
        status="candidate",
        time_start=now - 7200,
        time_end=now - 3600,
        primary_entity_ids=["user:alice", "project:magi"],
        source_event_count=5,
    )
    await store.create_episode(
        episode_id=eid2,
        status="candidate",
        time_start=now - 3300,  # 5 min after eid1 ends
        time_end=now - 1800,
        primary_entity_ids=["user:alice", "project:magi"],
        source_event_count=3,
    )
    # Back each declared count with real, distinct membership so the merged
    # count is derivable from episode_events (not hand-summed arithmetic).
    await store.add_episode_events(
        episode_id=eid1, event_ids=["evt-1", "evt-2", "evt-3", "evt-4", "evt-5"]
    )
    await store.add_episode_events(
        episode_id=eid2, event_ids=["evt-a", "evt-b", "evt-c"]
    )

    # Promote both manually
    await store.update_episode(episode_id=eid1, status="active")
    await store.update_episode(episode_id=eid2, status="active")

    stats = await consolidate_episodes(store)
    assert stats.merged >= 1

    ep1 = await store.get_episode(episode_id=eid1)
    ep2 = await store.get_episode(episode_id=eid2)
    assert ep2["status"] == "merged"
    assert ep1["status"] == "active"
    # Survivor count is derived from true membership: 5 (eid1) + 3 moved (eid2).
    assert ep1["source_event_count"] == 8
    assert ep1["source_event_count"] == await store.count_episode_events(
        episode_id=eid1
    )


@pytest.mark.asyncio
async def test_consolidation_invalidates_sparse(tmp_path):
    """Episodes with fewer than 2 events should be invalidated."""
    from magi.memory.l2.store import L2CognitionStore
    from magi.memory.l2.episode_formation import consolidate_episodes

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    eid = str(uuid.uuid4())
    await store.create_episode(
        episode_id=eid,
        time_start=time.time() - 3600,
        time_end=time.time(),
        source_event_count=1,
    )
    # Add only 1 event
    await store.add_episode_events(episode_id=eid, event_ids=["evt-1"])

    stats = await consolidate_episodes(store)
    assert stats.invalidated >= 1

    ep = await store.get_episode(episode_id=eid)
    assert ep["status"] == "invalidated"


@pytest.mark.asyncio
async def test_episode_hierarchy(tmp_path):
    """Parent-child episode relationship via parent_episode_id."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    parent_id = str(uuid.uuid4())
    child1_id = str(uuid.uuid4())
    child2_id = str(uuid.uuid4())

    await store.create_episode(
        episode_id=parent_id,
        episode_type="trip",
        time_start=1000.0,
        time_end=5000.0,
        source_event_count=10,
    )
    await store.create_episode(
        episode_id=child1_id,
        episode_type="visit",
        time_start=1000.0,
        time_end=2000.0,
        parent_episode_id=parent_id,
        source_event_count=3,
    )
    await store.create_episode(
        episode_id=child2_id,
        episode_type="visit",
        time_start=3000.0,
        time_end=4000.0,
        parent_episode_id=parent_id,
        source_event_count=4,
    )

    children = await store.list_episodes(parent_episode_id=parent_id)
    assert len(children) == 2
    child_ids = {c["episode_id"] for c in children}
    assert child1_id in child_ids
    assert child2_id in child_ids


@pytest.mark.asyncio
async def test_episode_fts_search(tmp_path):
    """FTS search returns episodes matching query."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    eid = str(uuid.uuid4())
    await store.create_episode(
        episode_id=eid,
        time_start=100.0,
        time_end=200.0,
        source_event_count=3,
    )
    await store.update_episode(
        episode_id=eid,
        summary="Afternoon coding session at the office",
        label="Coding at office",
    )
    await store.index_episode_fts(
        episode_id=eid,
        summary="Afternoon coding session at the office",
        label="Coding at office",
        user_label="",
    )

    results = await store.search_episodes_fts(query="coding")
    assert len(results) >= 1
    assert results[0]["episode_id"] == eid

    # Nonexistent query
    empty = await store.search_episodes_fts(query="zzznonexistent")
    assert len(empty) == 0


@pytest.mark.asyncio
async def test_clear_includes_episodes(tmp_path):
    """clear() should also delete episodes and episode_events."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    eid = str(uuid.uuid4())
    await store.create_episode(
        episode_id=eid, time_start=100.0, time_end=200.0,
    )
    await store.add_episode_events(episode_id=eid, event_ids=["evt-1"])

    await store.clear()

    assert await store.count_episodes() == 0
    events = await store.list_episode_events(episode_id=eid)
    assert len(events) == 0


@pytest.mark.asyncio
async def test_episode_models():
    """Verify EpisodeWrite and EpisodeCandidateJob dataclass contracts."""
    from magi.memory.l2.models import EpisodeCandidateJob, EpisodeConsolidationStats, EpisodeWrite

    ew = EpisodeWrite(
        episode_id="ep-1",
        episode_type="session",
        time_start=100.0,
        time_end=200.0,
        primary_entity_ids=["user:alice"],
    )
    d = ew.to_dict()
    assert d["episode_id"] == "ep-1"
    assert d["primary_entity_ids"] == ["user:alice"]

    ew2 = EpisodeWrite.from_dict(d)
    assert ew2.episode_id == "ep-1"

    job = EpisodeCandidateJob(
        event_id="evt-1",
        event_timestamp=1000.0,
        entity_ids=["user:alice"],
    )
    jd = job.to_dict()
    assert jd["event_id"] == "evt-1"

    job2 = EpisodeCandidateJob.from_dict(jd)
    assert job2.event_id == "evt-1"

    stats = EpisodeConsolidationStats(promoted=3, merged=1)
    sd = stats.to_dict()
    assert sd["promoted"] == 3
    assert sd["merged"] == 1
