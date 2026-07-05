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
        episode_id=eid,
        time_start=100.0,
        time_end=200.0,
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
        episode_id=eid,
        time_start=100.0,
        time_end=200.0,
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
    assert added2 == 1
    events_after = await store.list_episode_events(episode_id=eid)
    assert len(events_after) == 4

    # Remove events
    removed = await store.remove_episode_events(episode_id=eid, event_ids=["evt-1", "evt-3"])
    assert removed == 2
    remaining = await store.list_episode_events(episode_id=eid)
    assert len(remaining) == 2


@pytest.mark.asyncio
async def test_count_episode_events_dedups_and_matches_membership(l2_store_with_schema):
    """count_episode_events reflects true distinct membership despite re-adds."""
    store = l2_store_with_schema
    await store.create_episode(episode_id="a", time_start=1, time_end=2, source_event_count=0)
    await store.add_episode_events(episode_id="a", event_ids=["e1", "e2"])
    await store.add_episode_events(
        episode_id="a", event_ids=["e2", "e3"]
    )  # e2 duplicate -> ignored
    assert await store.count_episode_events(episode_id="a") == 3


@pytest.mark.asyncio
async def test_merge_episodes_moves_events_and_terminates_absorbed(l2_store_with_schema):
    store = l2_store_with_schema
    await store.create_episode(
        episode_id="a",
        status="active",
        time_start=1,
        time_end=2,
        primary_entity_ids=["user:alice"],
        primary_topic_keys=["work"],
    )
    await store.create_episode(
        episode_id="b",
        status="active",
        time_start=3,
        time_end=4,
        primary_entity_ids=["user:bob"],
        primary_place_ids=["place:office"],
        primary_topic_keys=["launch"],
    )
    await store.add_episode_events(episode_id="a", event_ids=["e1", "e2"])
    await store.add_episode_events(episode_id="b", event_ids=["e2", "e3"])

    survivor = await store.merge_episodes(survivor_id="a", absorbed_id="b")

    absorbed = await store.get_episode(episode_id="b")
    assert survivor is not None
    assert absorbed is not None
    assert absorbed["status"] == "merged"
    assert absorbed["parent_episode_id"] == "a"
    assert survivor["time_start"] == 1
    assert survivor["time_end"] == 4
    assert survivor["source_event_count"] == 3
    assert await store.count_episode_events(episode_id="a") == 3
    assert await store.count_episode_events(episode_id="b") == 0
    assert survivor["primary_entity_ids"] == ["user:alice", "user:bob"]
    assert survivor["primary_place_ids"] == ["place:office"]
    assert survivor["primary_topic_keys"] == ["work", "launch"]


@pytest.mark.asyncio
async def test_split_episode_creates_two_active_children_and_invalidates_original(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    await store.create_episode(
        episode_id="ep",
        status="active",
        time_start=1,
        time_end=4,
        primary_entity_ids=["place:japan"],
    )
    await store.add_episode_events(episode_id="ep", event_ids=["e1", "e2", "e3", "e4"])

    result = await store.split_episode(
        source_episode_id="ep",
        left_episode_id="ep-a",
        right_episode_id="ep-b",
        left_event_ids=["e1", "e2"],
        right_event_ids=["e3", "e4"],
        left_time_start=1,
        left_time_end=2,
        right_time_start=3,
        right_time_end=4,
    )

    assert result is not None
    original = await store.get_episode(episode_id="ep")
    left = await store.get_episode(episode_id="ep-a")
    right = await store.get_episode(episode_id="ep-b")
    assert original["status"] == "invalidated"
    assert left["status"] == "active"
    assert right["status"] == "active"
    assert left["parent_episode_id"] == "ep"
    assert right["parent_episode_id"] == "ep"
    assert await store.count_episode_events(episode_id="ep") == 0
    assert await store.count_episode_events(episode_id="ep-a") == 2
    assert await store.count_episode_events(episode_id="ep-b") == 2


@pytest.mark.asyncio
async def test_split_episode_preserves_membership_metadata(l2_store_with_schema):
    store = l2_store_with_schema
    await store.create_episode(
        episode_id="ep",
        status="active",
        time_start=1,
        time_end=4,
    )
    await store.add_episode_events(
        episode_id="ep",
        event_ids=["e1"],
        membership_role="anchor",
        membership_confidence=0.9,
    )
    await store.add_episode_events(
        episode_id="ep",
        event_ids=["e2"],
        membership_role="supporting",
        membership_confidence=0.4,
    )

    result = await store.split_episode(
        source_episode_id="ep",
        left_episode_id="ep-a",
        right_episode_id="ep-b",
        left_event_ids=["e1"],
        right_event_ids=["e2"],
        left_time_start=1,
        left_time_end=2,
        right_time_start=3,
        right_time_end=4,
    )

    assert result is not None
    left_events = await store.list_episode_events(episode_id="ep-a")
    right_events = await store.list_episode_events(episode_id="ep-b")
    assert left_events[0]["membership_role"] == "anchor"
    assert left_events[0]["membership_confidence"] == 0.9
    assert right_events[0]["membership_role"] == "supporting"
    assert right_events[0]["membership_confidence"] == 0.4


@pytest.mark.asyncio
async def test_find_episode_for_event(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    eid = str(uuid.uuid4())
    await store.create_episode(
        episode_id=eid,
        time_start=100.0,
        time_end=200.0,
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
async def test_streaming_candidate_formation_does_not_extend_without_theme(tmp_path):
    """Events with no entity or topic signals must not attach by recency alone."""
    from magi.memory.l2.store import L2CognitionStore
    from magi.memory.l2.episode_formation import assign_events_to_episode
    from magi.memory.l2.models import EpisodeCandidateJob

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    now = time.time()
    ep1_id = await assign_events_to_episode(
        store,
        [
            EpisodeCandidateJob(
                event_id="evt-themed",
                event_timestamp=now,
                entity_ids=["user:alice"],
                topic_keys=["coding"],
            ),
        ],
    )

    ep2_id = await assign_events_to_episode(
        store,
        [
            EpisodeCandidateJob(
                event_id="evt-empty",
                event_timestamp=now + 60,
            ),
        ],
    )

    assert ep2_id != ep1_id
    assert await store.count_episode_events(episode_id=ep1_id) == 1
    assert await store.count_episode_events(episode_id=ep2_id) == 1


@pytest.mark.asyncio
async def test_streaming_candidate_formation_does_not_extend_on_only_generic_entity(tmp_path):
    from magi.memory.l2.store import L2CognitionStore
    from magi.memory.l2.episode_formation import assign_events_to_episode
    from magi.memory.l2.models import EpisodeCandidateJob

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    now = time.time()
    ep1_id = await assign_events_to_episode(
        store,
        [
            EpisodeCandidateJob(
                event_id="evt-generic-1",
                event_timestamp=now,
                entity_ids=["user:local_user"],
            ),
        ],
    )

    ep2_id = await assign_events_to_episode(
        store,
        [
            EpisodeCandidateJob(
                event_id="evt-generic-2",
                event_timestamp=now + 60,
                entity_ids=["user:local_user"],
            ),
        ],
    )

    assert ep2_id != ep1_id
    assert await store.count_episode_events(episode_id=ep1_id) == 1
    assert await store.count_episode_events(episode_id=ep2_id) == 1


@pytest.mark.asyncio
async def test_streaming_candidate_formation_extends_existing_by_topic(tmp_path):
    """Topic overlap can extend a recent candidate even without entity overlap."""
    from magi.memory.l2.store import L2CognitionStore
    from magi.memory.l2.episode_formation import assign_events_to_episode
    from magi.memory.l2.models import EpisodeCandidateJob

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    now = time.time()
    ep1_id = await assign_events_to_episode(
        store,
        [
            EpisodeCandidateJob(
                event_id="evt-topic-1",
                event_timestamp=now,
                topic_keys=["topic:coding"],
            ),
        ],
    )

    ep2_id = await assign_events_to_episode(
        store,
        [
            EpisodeCandidateJob(
                event_id="evt-topic-2",
                event_timestamp=now + 60,
                topic_keys=["topic:coding"],
            ),
        ],
    )

    assert ep2_id == ep1_id
    assert await store.count_episode_events(episode_id=ep1_id) == 2


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
        EpisodeCandidateJob(event_id="evt-1", event_timestamp=now, entity_ids=["user:alice"]),
        EpisodeCandidateJob(event_id="evt-2", event_timestamp=now + 1, entity_ids=["user:alice"]),
    ]
    ep1_id = await assign_events_to_episode(store, first_jobs)

    # Second batch 10 min later lands on the SAME candidate, but re-includes
    # evt-2 (already a member) alongside a fresh evt-3.
    second_jobs = [
        EpisodeCandidateJob(event_id="evt-2", event_timestamp=now + 600, entity_ids=["user:alice"]),
        EpisodeCandidateJob(event_id="evt-3", event_timestamp=now + 601, entity_ids=["user:alice"]),
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
    await store.add_episode_events(episode_id=eid2, event_ids=["evt-a", "evt-b", "evt-c"])

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
    assert ep1["source_event_count"] == await store.count_episode_events(episode_id=eid1)


@pytest.mark.asyncio
async def test_consolidation_does_not_merge_on_only_generic_entity_overlap(tmp_path):
    """Adjacent active episodes should not merge solely because both mention local user."""
    from magi.memory.l2.store import L2CognitionStore
    from magi.memory.l2.episode_formation import consolidate_episodes

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    now = time.time()
    eid1 = str(uuid.uuid4())
    eid2 = str(uuid.uuid4())
    await store.create_episode(
        episode_id=eid1,
        status="active",
        time_start=now - 7200,
        time_end=now - 3600,
        primary_entity_ids=["user:local_user"],
        source_event_count=3,
    )
    await store.create_episode(
        episode_id=eid2,
        status="active",
        time_start=now - 3300,
        time_end=now - 1800,
        primary_entity_ids=["user:local_user"],
        source_event_count=3,
    )
    await store.add_episode_events(episode_id=eid1, event_ids=["evt-generic-a"])
    await store.add_episode_events(episode_id=eid2, event_ids=["evt-generic-b"])

    stats = await consolidate_episodes(store)

    assert stats.merged == 0
    ep1 = await store.get_episode(episode_id=eid1)
    ep2 = await store.get_episode(episode_id=eid2)
    assert ep1["status"] == "active"
    assert ep2["status"] == "active"


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
async def test_episode_fts_search_or_combines_terms(tmp_path):
    """Multi-term queries match episodes containing any term, not the exact phrase."""
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
    await store.index_episode_fts(
        episode_id=eid,
        summary="Discussed AI tooling with Sarah over coffee",
        label="Chat with Sarah",
        user_label="",
    )

    # Terms appear in the text but never adjacently as a phrase.
    results = await store.search_episodes_fts(query="Sarah tooling")
    assert [item["episode_id"] for item in results] == [eid]

    # One matching term out of several is enough.
    partial = await store.search_episodes_fts(query="Sarah zzznonexistent")
    assert [item["episode_id"] for item in partial] == [eid]

    # Blank queries return nothing instead of raising FTS syntax errors.
    assert await store.search_episodes_fts(query="   ") == []


@pytest.mark.asyncio
async def test_clear_includes_episodes(tmp_path):
    """clear() should also delete episodes and episode_events."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    eid = str(uuid.uuid4())
    await store.create_episode(
        episode_id=eid,
        time_start=100.0,
        time_end=200.0,
    )
    await store.add_episode_events(episode_id=eid, event_ids=["evt-1"])

    await store.clear()

    assert await store.count_episodes() == 0
    events = await store.list_episode_events(episode_id=eid)
    assert len(events) == 0


async def _make_mature_candidate(store, *, episode_id, source_event_count, primary_entity_ids):
    """Create a candidate old enough and rich enough that consolidate promotes it.

    Backs the declared count with real distinct membership so the consolidation
    invalidate/merge scans see a healthy episode, and backdates created_at so the
    30-min promotion-age gate passes.
    """
    from magi.core.sqlite import sqlite_connection_async

    now = time.time()
    await store.create_episode(
        episode_id=episode_id,
        time_start=now - 7200,
        time_end=now - 3600,  # 1 hour duration (> standout 20-min floor)
        primary_entity_ids=primary_entity_ids,
        source_event_count=source_event_count,
    )
    await store.add_episode_events(
        episode_id=episode_id,
        event_ids=[f"{episode_id}-evt-{i}" for i in range(source_event_count)],
    )
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute(
            "UPDATE episodes SET created_at = ? WHERE episode_id = ?",
            (now - 7200, episode_id),
        )
        await db.commit()


@pytest.mark.asyncio
async def test_promoted_non_standout_visible_via_status_active(l2_store_with_schema):
    """Page visibility is decoupled from standout: list_episodes(status='active')
    returns a promoted episode even when magi_standout is False (finding #14)."""
    from magi.memory.l2.episode_formation import consolidate_episodes

    store = l2_store_with_schema
    # 4 events: above MIN_EVENTS_TO_PROMOTE (3), below STANDOUT_MIN_EVENTS →
    # gets promoted to active but NOT flagged standout.
    await _make_mature_candidate(
        store,
        episode_id="ep-plain",
        source_event_count=4,
        primary_entity_ids=["a"],
    )

    await consolidate_episodes(store)

    ep = await store.get_episode(episode_id="ep-plain")
    assert ep["status"] == "active"
    assert ep["magi_standout"] is False

    active = await store.list_episodes(status="active")
    assert "ep-plain" in {e["episode_id"] for e in active}


@pytest.mark.asyncio
async def test_consolidate_does_not_flip_standout_between_passes(l2_store_with_schema):
    """Single-writer / idempotent: running consolidate_episodes twice must not
    flip an episode's magi_standout (finding #14 — no double-write reversal)."""
    from magi.memory.l2.episode_formation import consolidate_episodes

    store = l2_store_with_schema
    # 10 events + 2 entities + 1h duration → passes the standout gate.
    await _make_mature_candidate(
        store,
        episode_id="ep-standout",
        source_event_count=10,
        primary_entity_ids=["a", "b"],
    )

    await consolidate_episodes(store)
    first = await store.get_episode(episode_id="ep-standout")
    assert first["status"] == "active"
    assert first["magi_standout"] is True

    # Second pass: the episode is already active; consolidate must not demote it.
    await consolidate_episodes(store)
    second = await store.get_episode(episode_id="ep-standout")
    assert second["magi_standout"] is True


@pytest.mark.asyncio
async def test_rescore_does_not_demote_formation_flagged_standout(l2_store_with_schema):
    """Single-writer invariant (finding #14): consolidate_episodes is the canonical
    writer of magi_standout. The 2-hour standout rescore must never flip a
    formation-flagged episode back to magi_standout=False, even when its own
    heuristic score is below threshold."""
    from magi.media.source_registry import MediaSourceRegistry
    from magi.timeline.standout.scheduler_contrib import StandoutScoringSchedulerContrib

    store = l2_store_with_schema
    now = time.time()
    # A SHORT dense episode that the formation gate flagged standout, but whose
    # duration is below the rescore's 90-min
    # WEIGHT_DURATION threshold and has no photos → rescore heuristic score = 0.
    await store.create_episode(
        episode_id="ep-flagged",
        status="active",
        time_start=now - 600,
        time_end=now,  # 10 minutes — below rescore duration threshold
        primary_entity_ids=[],  # no first-seen entity bonus either
        source_event_count=20,
        magi_standout=True,  # set by the canonical formation writer
    )

    registry = MediaSourceRegistry()  # empty — no photos
    contrib = StandoutScoringSchedulerContrib(l2_store=store, media_registry=registry)

    class _Ctx:
        triggered_at = now
        manual = False

    await contrib._handle_rescore(_Ctx())

    ep = await store.get_episode(episode_id="ep-flagged")
    # Rescore may refresh standout_score/reason metadata, but must NOT demote the
    # formation-set flag — otherwise the episode silently drops out of the reel.
    assert ep["magi_standout"] is True


@pytest.mark.asyncio
async def test_invalidated_standout_not_returned_by_standout_query(l2_store_with_schema):
    """Terminal-state leak (finding #16): an episode that was standout but later
    became 'invalidated' (or 'merged') must NOT appear in the standout list."""
    store = l2_store_with_schema
    now = time.time()
    await store.create_episode(
        episode_id="ep-gone",
        status="active",
        time_start=now - 3600,
        time_end=now - 1800,
        primary_entity_ids=["a", "b"],
        source_event_count=5,
        magi_standout=True,
    )
    # Sanity: while active it IS a standout.
    standouts = await store.list_standout_episodes(limit=50)
    assert "ep-gone" in {e["episode_id"] for e in standouts}

    # Terminal state — the standout query must drop it.
    await store.update_episode(episode_id="ep-gone", status="invalidated")
    standouts_after = await store.list_standout_episodes(limit=50)
    assert "ep-gone" not in {e["episode_id"] for e in standouts_after}

    # Same for a merged episode.
    await store.create_episode(
        episode_id="ep-merged",
        status="active",
        time_start=now - 3600,
        time_end=now - 1800,
        primary_entity_ids=["c", "d"],
        source_event_count=5,
        magi_standout=True,
    )
    await store.update_episode(episode_id="ep-merged", status="merged")
    standouts_merged = await store.list_standout_episodes(limit=50)
    assert "ep-merged" not in {e["episode_id"] for e in standouts_merged}


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
