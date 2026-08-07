"""Plugin-contributed graph-derived assertion specs."""

from __future__ import annotations

from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
from typing import Any, AsyncIterator
from unittest.mock import MagicMock, patch

import aiosqlite
import pytest

from magi.memory.l2.assertions.derived_rules import (
    build_graph_derived_rules_from_profiles,
    evaluate_graph_derived_assertion_rule,
)
from magi.memory.l2.extraction_profiles import build_extraction_profile_registry
from magi_plugin_sdk import ExtractionProfileSpec

from .test_derive_schedule import (
    _build_config,
    _make_dummy_context,
    _seed_canonical_name,
)
from .test_derived_assertion_rules import _EvidenceEventStore, _seed_edge


@asynccontextmanager
async def _memory_operation_guard() -> AsyncIterator[None]:
    yield


def _music_profile_spec(
    *,
    invalid: bool = False,
    object_types: list[str] | None = None,
) -> ExtractionProfileSpec:
    return ExtractionProfileSpec(
        profile_id="source.netease_music",
        source_types=["netease_music"],
        allowed_entity_types=["media"],
        allowed_predicates=["LISTENED"],
        allowed_assertion_families=["interest_profile"],
        allowed_assertion_traits=["music.*"],
        allow_assertion=False,
        derived_assertion_specs=[
            {
                "rule_id": "netease_music.listened",
                "source_predicates": ["LIKES" if invalid else "LISTENED"],
                "source_types": ["chrome_history" if invalid else "netease_music"],
                "trait_family": "mood" if invalid else "interest_profile",
                "trait_name_template": "mood.{object_slug}" if invalid else "music.{object_slug}",
                "min_observations": 2,
                "min_distinct_days": 2,
                "signal_preset": "sustained_engagement",
                **({"object_types": object_types} if object_types is not None else {}),
                "source_domains": ["external_activity"],
                "value_strategy": "canonical_name",
            }
        ],
    )


async def _rows_for_trait(store: Any, *, trait_name: str) -> list[dict[str, Any]]:
    async with aiosqlite.connect(store.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM tom_trait_assertions WHERE trait_name = ? ORDER BY created_at ASC",
            (trait_name,),
        ) as cursor:
            rows = await cursor.fetchall()
    return [dict(row) for row in rows]


def test_valid_plugin_spec_builds_derived_rule():
    profiles = build_extraction_profile_registry([_music_profile_spec()])

    rules = build_graph_derived_rules_from_profiles(profiles)

    assert len(rules) == 1
    rule = rules[0]
    assert rule.rule_id == "netease_music.listened"
    assert rule.source_predicates == ("LISTENED",)
    assert rule.source_types == ("netease_music",)
    assert rule.trait_family == "interest_profile"
    assert rule.trait_name_template == "music.{object_slug}"
    assert rule.signal_preset.value == "sustained_engagement"


def test_invalid_plugin_spec_is_ignored():
    profiles = build_extraction_profile_registry([_music_profile_spec(invalid=True)])

    assert build_graph_derived_rules_from_profiles(profiles) == ()


def test_plugin_spec_with_unknown_object_type_is_ignored():
    profiles = build_extraction_profile_registry([
        _music_profile_spec(object_types=["media", "unknown-kind"])
    ])

    assert build_graph_derived_rules_from_profiles(profiles) == ()


@pytest.mark.asyncio
async def test_plugin_rule_writes_inferred_assertion(l2_store_with_schema):
    store = l2_store_with_schema
    await _seed_edge(
        store,
        object_id="media:song-a",
        object_type="media",
        predicate="LISTENED",
        source_type="netease_music",
        event_ids=["song-a-1", "song-a-2"],
    )
    await _seed_canonical_name(store, entity_id="media:song-a", canonical_name="Song A", entity_type="media")
    profiles = build_extraction_profile_registry([_music_profile_spec()])
    rules = build_graph_derived_rules_from_profiles(profiles)

    stats = await evaluate_graph_derived_assertion_rule(
        store,
        rules[0],
        l1_store=_EvidenceEventStore(),
    )

    assert stats["assertions_written"] == 1
    rows = await _rows_for_trait(store, trait_name="music.song-a")
    assert len(rows) == 1
    assert rows[0]["trait_value"] == "Song A"
    assert rows[0]["source_domain"] == "external_activity"


@pytest.mark.asyncio
async def test_plugin_rule_does_not_overwrite_authoritative_assertion(l2_store_with_schema):
    store = l2_store_with_schema
    await store.upsert_assertion_candidate(
        {
            "entity_id": "user:local_user",
            "entity_type": "user",
            "trait_family": "preference_profile",
            "trait_name": "music.song-a",
            "trait_value": "User Stated Song",
            "confidence_score": 0.8,
            "evidence_events": ["user-1"],
            "volatility_index": 0.2,
            "source_domain": "user_authored",
            "inference_depth": "topology_only",
            "validation_state": "tentative",
            "first_inferred_at": 1_710_000_000.0,
            "last_validated_at": 1_710_000_000.0,
            "target_entity_id": "media:song-a",
            "target_entity_type": "media",
            "target_scope": "entity_bound",
            "temporal_scope": "stable",
            "decay_policy": "evidence_only",
            "natural_summary": "User stated a song preference",
        }
    )
    await _seed_edge(
        store,
        object_id="media:song-a",
        object_type="media",
        predicate="LISTENED",
        source_type="netease_music",
        event_ids=["song-a-1", "song-a-2"],
    )
    await _seed_canonical_name(store, entity_id="media:song-a", canonical_name="Song A", entity_type="media")
    profiles = build_extraction_profile_registry([_music_profile_spec()])
    rule = build_graph_derived_rules_from_profiles(profiles)[0]

    await evaluate_graph_derived_assertion_rule(
        store,
        rule,
        l1_store=_EvidenceEventStore(),
    )

    rows = await _rows_for_trait(store, trait_name="music.song-a")
    active = [row for row in rows if row["status"] != "shadow"]
    shadow = [row for row in rows if row["status"] == "shadow"]
    assert [row["trait_value"] for row in active] == ["User Stated Song"]
    assert [row["trait_value"] for row in shadow] == ["Song A"]


@pytest.mark.asyncio
async def test_derive_schedule_runs_plugin_derived_rules(tmp_path):
    from _shared.memory_schema import apply_memory_shared_schema
    from magi.memory.l2.store import L2CognitionStore

    db_path = str(tmp_path / "l2.db")
    await apply_memory_shared_schema(db_path)
    store = L2CognitionStore(db_path=db_path)
    await store.initialize()
    await _seed_edge(
        store,
        object_id="media:song-b",
        object_type="media",
        predicate="LISTENED",
        source_type="netease_music",
        event_ids=["song-b-1", "song-b-2"],
        entity_id="user:local_user",
    )
    await _seed_canonical_name(store, entity_id="media:song-b", canonical_name="Song B", entity_type="media")

    catalog_mock = MagicMock()
    catalog_mock.db_path = db_path
    pipeline_mock = SimpleNamespace(
        _cognition_store=store,
        _extraction_profile_provider=lambda: [_music_profile_spec()],
    )
    unified_mock = SimpleNamespace(
        l1=_EvidenceEventStore(),
        l2_entity_catalog=catalog_mock,
        l2_pipeline=pipeline_mock,
        memory_operation_guard=_memory_operation_guard,
    )
    cfg_mock = _build_config(
        interest_aggregation_enabled=False,
        shadow_conflict_notification_enabled=False,
    )

    from magi.memory.l2.derive_schedule import handle_l2_derive

    with (
        patch("magi.memory.l2.derive_schedule.get_unified_memory", return_value=unified_mock),
        patch("magi.memory.l2.derive_schedule.get_config", return_value=cfg_mock),
    ):
        result = await handle_l2_derive(_make_dummy_context())

    assert result.success is True
    assert result.stats["plugin_derived_assertions_written"] == 1
    rows = await _rows_for_trait(store, trait_name="music.song-b")
    assert len(rows) == 1
    assert json.loads(rows[0]["evidence_events"]) == ["song-b-1", "song-b-2"]
