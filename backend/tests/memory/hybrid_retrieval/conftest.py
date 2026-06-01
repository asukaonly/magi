"""Shared fixtures for hybrid_retrieval memory tests."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import pytest_asyncio

from _shared.memory_schema import apply_memory_shared_schema
from magi.memory.evidence import EvidenceClass
from magi.memory.l2.store import L2CognitionStore


@pytest_asyncio.fixture
async def seeded_l2_store(tmp_path: Path) -> L2CognitionStore:
    """L2 store seeded with the production-bug scenario:
    many EXTERNAL_OBSERVATION INTERESTED_IN edges (Chrome history) plus
    one USER_SELF_REPORT LIKES edge (user's declared name preference).
    """
    db_path = tmp_path / "l2.sqlite"
    await apply_memory_shared_schema(str(db_path))
    store = L2CognitionStore(db_path=str(db_path))
    await store.initialize()
    now = time.time()

    # Many EXTERNAL_OBSERVATION INTERESTED_IN edges (Chrome history)
    for org_id in ("74f953b57f75", "cbff460f1cac", "abc123def456"):
        await store.upsert_knowledge_edge(
            subject_id="user:local_user",
            subject_type="person",
            predicate="INTERESTED_IN",
            object_id=f"organization:{org_id}",
            object_type="organization",
            evidence_event_ids=[f"evt_{uuid.uuid4().hex[:12]}"],
            confidence=0.99,
            observed_at=now - 3 * 86400,
            source_type="chrome_history",
            evidence_class=EvidenceClass.EXTERNAL_OBSERVATION.label,
        )

    # One USER_SELF_REPORT LIKES edge ("叫我子涵或者哈基米" projected as preference)
    await store.upsert_knowledge_edge(
        subject_id="user:local_user",
        subject_type="person",
        predicate="LIKES",
        object_id="preference:address_form:子涵",
        object_type="preference_value",
        evidence_event_ids=[f"evt_{uuid.uuid4().hex[:12]}"],
        confidence=1.0,
        observed_at=now - 4 * 86400,
        source_type="conversation",
        evidence_class=EvidenceClass.USER_SELF_REPORT.label,
    )
    return store
