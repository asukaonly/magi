"""End-to-end plumbing: an EXTERNAL interest observation surfaces in the user
snapshot as an *inferred* preference.

This is the integration proof for "行为兴趣进画像 · Plan A". It drives the real
L2 pipeline (``UnifiedMemoryStore.ingest_event`` -> staging -> extract worker ->
phase1/phase2 -> validation -> assertion upsert -> snapshot assembly) with only
the phase1/phase2 *LLM* stubbed, and asserts the resulting snapshot carries the
preference with ``source_tier == "inferred"`` (and that it is an active
assertion, not a ``shadow``, since there is no conflicting authoritative row).

The chain under test:
    external (author_type="external") event
      -> evidence class ``external_observation`` (policy ``assertion_scope=interest``)
      -> stubbed phase2 emits a ``taste_profile`` ``assertion_candidate``
      -> ``_validate_phase2_assertions`` accepts it (family is allowlisted)
      -> ``_upsert_assertion`` writes it active with ``source_domain=external_activity``
      -> ``refresh_entity_snapshot`` -> ``preferences[...]["source_tier"] == "inferred"``

Harness: reuses ``_FakeAdapter`` / ``_FakeScenarioPool`` and the
schema-migrating ``UnifiedMemoryStore`` subclass from ``test_pipeline`` — the
same fixtures the rest of the L2 pipeline integration tests use to inject a
fake phase1/phase2 LLM.

Why two ``supporting_event_ids`` on the stubbed candidate: a brand-new
non-temporary assertion needs ``evidence_count >= 2`` to graduate from
``tentative`` to ``corroborated`` (see ``assertions/state_machine.py``). Only
``stable``/``corroborated`` assertions are read as *active* by
``refresh_entity_snapshot`` and therefore feed ``_add_assertion_preferences``.
A single-evidence candidate would persist as ``tentative`` and never reach the
snapshot — which is a property of the assertion lifecycle, not of Plan A's
scope/source-tier wiring that this test targets.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
from pathlib import Path

import pytest

from magi.events.events import EventLevel

from .test_pipeline import _FakeAdapter, _FakeScenarioPool, UnifiedMemoryStore


def _external_interest_phase1() -> str:
    """Phase 1: one concrete activity entity + an INTERESTED_IN claim.

    Non-empty content so the pipeline proceeds to phase 2 (an empty phase 1
    short-circuits before integration).
    """
    return json.dumps(
        {
            "entities": [
                {
                    "surface": "rock climbing",
                    "normalized_name": "rock climbing",
                    "entity_type": "activity",
                    "specificity": "concrete",
                    "resolved_id": None,
                    "is_new": True,
                    "alias_signals": [],
                    "confidence": 0.9,
                }
            ],
            "fact_claims": [
                {
                    "subject_ref": "user:self",
                    "predicate": "INTERESTED_IN",
                    "object_ref": "rock climbing",
                    "object_type": "activity",
                    "fact_kind": "stable_preference",
                    "polarity": "positive",
                    "specificity": "concrete",
                    "evidence_text": "browsed rock climbing gear reviews",
                    "confidence": 0.8,
                    "supporting_event_ids": ["evt-ext-interest-1"],
                }
            ],
            "resolved_refs": [],
            "diagnostics": {"entity_status": "none"},
        }
    )


def _external_interest_phase2() -> str:
    """Phase 2: emit a ``taste_profile`` assertion attributed to ``user:self``.

    Two ``supporting_event_ids`` so the upsert graduates the fresh assertion to
    ``corroborated`` (snapshot-visible) instead of leaving it ``tentative``.
    """
    return json.dumps(
        {
            "graph_edges": [],
            "refinements": [],
            "assertion_candidates": [
                {
                    "entity_ref": "user:self",
                    "entity_type": "user",
                    "trait_family": "taste_profile",
                    "trait_name": "taste.activity",
                    "trait_value": "rock climbing",
                    "natural_summary": "Shows interest in rock climbing",
                    "inference_depth": "defensive_psychology",
                    "volatility_index": 0.2,
                    "confidence": 0.7,
                    "evidence_texts": ["browsed rock climbing gear reviews"],
                    "supporting_event_ids": [
                        "evt-ext-interest-1",
                        "evt-ext-interest-2",
                    ],
                }
            ],
            "contradiction_hints": [],
        }
    )


async def _wait_for_assertions(store, *, entity_id: str, attempts: int = 300):
    """Poll until the extract worker has written an assertion (or give up)."""
    rows: list = []
    for _ in range(attempts):
        rows = await store.l2.list_tom_assertions(entity_id=entity_id, limit=50)
        if rows:
            return rows
        await asyncio.sleep(0.02)
    return rows


@pytest.mark.asyncio
async def test_external_interest_surfaces_as_inferred_preference_in_snapshot():
    """One external interest observation -> snapshot preference, source_tier=inferred."""
    adapter = _FakeAdapter([_external_interest_phase1(), _external_interest_phase2()])
    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        store = UnifiedMemoryStore(
            l1_db_path=str(base / "l1_events.db"),
            memory_db_path=str(base / "memory.db"),
            persist_dir=str(base / "memories"),
            l2_batch_flush_interval_seconds=0,
            scenario_llm_pool=_FakeScenarioPool(adapter),
        )
        await store.initialize()
        try:
            # An external observation: a chrome-history-style SENSOR_EVENT.
            # normalize_runtime_event resolves this to
            # author_type="external" / memory_domain="external_activity", which
            # the evidence classifier maps to EXTERNAL_OBSERVATION
            # (assertion_scope="interest", allow_assertion_write=True).
            ingest_result = await store.ingest_event(
                {
                    "id": "evt-ext-interest-1",
                    "type": "SENSOR_EVENT",
                    "timestamp": time.time(),
                    "source": "chrome_history",
                    "level": EventLevel.INFO.value,
                    "data": {
                        "user_id": "u1",
                        "content": "browsed rock climbing gear reviews",
                        "author_type": "external",
                        "content_type": "observation",
                        "source_item_id": "web:evt-ext-interest-1",
                    },
                }
            )
            assert ingest_result["l1_written"] is True
            assert ingest_result["l2_job_enqueued"] is True

            rows = await _wait_for_assertions(store, entity_id="user:u1")

            # 1) The phase2 candidate was persisted (the interest scope + the
            #    allowlisted taste_profile family let it through the real
            #    _validate_phase2_assertions path for an external event).
            assert len(rows) == 1, f"expected exactly one assertion, got {rows!r}"
            row = rows[0]
            assert row["trait_family"] == "taste_profile"
            assert row["trait_name"] == "taste.activity"
            assert row["trait_value"] == "rock climbing"
            # Inferred from external activity, not user-authored.
            assert row["source_domain"] == "external_activity"
            # Active (corroborated), NOT a shadow — there is no conflicting
            # authoritative row, so the source-aware upsert writes it active.
            assert row.get("status") == "corroborated"
            assert row.get("status") != "shadow"
            assert row["validation_state"] != "shadow"

            # 2) The snapshot surfaces it as an *inferred* preference.
            snapshot = await store.l2.refresh_entity_snapshot(
                entity_id="user:u1", entity_type="user"
            )
            assert snapshot is not None
            preferences = snapshot.get("preferences") or {}
            assert "taste.activity" in preferences, (
                f"preference not in snapshot: {preferences!r}"
            )
            pref = preferences["taste.activity"]
            assert pref["value"] == "rock climbing"
            assert pref["family"] == "taste_profile"
            assert pref["source_tier"] == "inferred"
        finally:
            await store.shutdown()
