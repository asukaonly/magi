"""Verification tests for P1-D1: source-level cascade forgetting and public route reachability."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from _shared.memory_stores import build_memory_store
from magi.api.routers.memory import dependencies as memory_deps
from magi.api.routers.memory.router import memory_router
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.memory.event_contracts import IngestTarget, MemoryDomain, MemoryEvent, RetentionClass, TomDepth


def test_forget_source_route_is_exposed_on_public_router():
    """Verify POST /forget/source passes through _PUBLIC_ROUTE_METHODS allowlist."""
    public = _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"])
    matched = [
        route
        for route in public.routes
        if getattr(route, "path", None) == "/forget/source"
        and "POST" in (getattr(route, "methods", None) or set())
    ]
    assert len(matched) == 1


@pytest.mark.asyncio
async def test_forget_source_cascades_l1_l2_vectors_l3_and_archives_without_touching_other_sources(
    tmp_path: Path,
    monkeypatch,
):
    """Forgetting chrome clears chrome L1/L2/vec_l2_edges/L3/cold-archive while git remains 100% intact."""
    data_dir = tmp_path / "memory"
    archive_dir = data_dir / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    store = build_memory_store(
        l1_db_path=str(data_dir / "l1_events.db"),
        memory_db_path=str(data_dir / "memory.db"),
        enable_l0=False,
        enable_l1=True,
        enable_l2=True,
        enable_l3=True,
        enable_l4=False,
        archive_dir_path=str(archive_dir),
    )
    await store.initialize()
    try:
        # 1. Seed active Chrome and Git L1 events
        chrome_evt = MemoryEvent(
            event_id="evt-chrome-1",
            correlation_id="corr-chrome-1",
            timestamp=1_760_000_100.0,
            created_at=1_760_000_100.0,
            event_type="SOURCE_EVENT",
            source="chrome_history",
            source_item_id="chrome-item-1",
            memory_domain=MemoryDomain.EXTERNAL_ACTIVITY,
            ingest_target=IngestTarget.L1_ONLY,
            cognition_eligible=True,
            tom_depth=TomDepth.NONE,
            retention_class=RetentionClass.COMPRESSIBLE,
            session_id=None,
            turn_id=None,
            user_id="local_user",
            task_id=None,
            content="Visited awkward shopping page",
            author_type="external",
            content_type="observation",
            importance_score=0.5,
            level=1,
            metadata_json={"source_connection_id": "conn-chrome"},
        )
        git_evt = MemoryEvent(
            event_id="evt-git-1",
            correlation_id="corr-git-1",
            timestamp=1_760_000_200.0,
            created_at=1_760_000_200.0,
            event_type="SOURCE_EVENT",
            source="git_activity",
            source_item_id="git-item-1",
            memory_domain=MemoryDomain.EXTERNAL_ACTIVITY,
            ingest_target=IngestTarget.L1_ONLY,
            cognition_eligible=True,
            tom_depth=TomDepth.NONE,
            retention_class=RetentionClass.COMPRESSIBLE,
            session_id=None,
            turn_id=None,
            user_id="local_user",
            task_id=None,
            content="Committed async IPC refactor",
            author_type="external",
            content_type="observation",
            importance_score=0.5,
            level=1,
            metadata_json={"source_connection_id": "conn-git"},
        )
        await store.l1.store(chrome_evt)
        await store.l1.store(git_evt)

        # 2. Seed derived L2 edges + mock edge vector index purge tracking
        fake_edge_index = AsyncMock()
        store.l2.set_edge_vector_index(fake_edge_index)
        chrome_triple_id = await store.l2.upsert_knowledge_edge(
            subject_id="user:self",
            subject_type="user",
            predicate="VIEWED",
            object_id="site:awkward-shop",
            object_type="website",
            evidence_event_ids=["evt-chrome-1"],
            confidence=0.8,
            observed_at=1_760_000_100.0,
            source_type="chrome_history",
        )
        git_triple_id = await store.l2.upsert_knowledge_edge(
            subject_id="user:self",
            subject_type="user",
            predicate="COMMITTED_TO",
            object_id="repo:magi",
            object_type="software",
            evidence_event_ids=["evt-git-1"],
            confidence=0.9,
            observed_at=1_760_000_200.0,
            source_type="git_activity",
        )
        assert chrome_triple_id and git_triple_id

        # 3. Seed derived L3 summaries (one backed by chrome, one backed by git)
        from magi.memory.l3.models import L3Candidate

        await store.l3.upsert_candidate(
            candidate=L3Candidate(
                content="Browsed shopping site",
                source_event_ids=["evt-chrome-1"],
                summary_category="day",
            ),
            summary_overrides={
                "period_start": 1_760_000_000.0,
                "period_end": 1_760_086_400.0,
                "key_topics": ["shopping"],
            },
        )
        await store.l3.upsert_candidate(
            candidate=L3Candidate(
                content="Worked on magi git repository",
                source_event_ids=["evt-git-1"],
                summary_category="day",
            ),
            summary_overrides={
                "period_start": 1_760_086_400.0,
                "period_end": 1_760_172_800.0,
                "key_topics": ["magi"],
            },
        )

        # 4. Seed cold archive DB containing one archived chrome event and one archived git event
        archive_db = archive_dir / "2025-10.db"
        conn = sqlite3.connect(str(archive_db))
        try:
            conn.execute(
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
            conn.execute(
                """
                INSERT INTO archived_l1_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "evt-chrome-archived-1",
                    "2025-10-01",
                    1_760_000_000.0,
                    1_750_000_000.0,
                    "SOURCE_EVENT",
                    "chrome_history",
                    None,
                    "local_user",
                    json.dumps({"metadata_json": {"source_connection_id": "conn-chrome"}}),
                ),
            )
            conn.execute(
                """
                INSERT INTO archived_l1_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "evt-git-archived-1",
                    "2025-10-01",
                    1_760_000_000.0,
                    1_750_000_000.0,
                    "SOURCE_EVENT",
                    "git_activity",
                    None,
                    "local_user",
                    json.dumps({"metadata_json": {"source_connection_id": "conn-git"}}),
                ),
            )
            conn.commit()
        finally:
            conn.close()

        # 5. Invoke POST /api/memory/forget/source through the real public router allowlist
        monkeypatch.setattr(memory_deps, "_resolve_unified_memory", lambda: store)
        app = FastAPI()
        app.include_router(
            _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]),
            prefix="/api/memory",
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/memory/forget/source",
                json={"source_name": "chrome_history", "connection_id": "conn-chrome"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["source_name"] == "chrome_history"
        assert body["l1_events_deleted"] == 1
        assert body["archived_events_deleted"] == 1

        # 6. Verify Chrome active L1 is gone, Git active L1 is 100% intact
        chrome_active = await store.l1.query_events(source_filters=["chrome_history"], limit=20)
        git_active = await store.l1.query_events(source_filters=["git_activity"], limit=20)
        assert chrome_active == []
        assert [row["event_id"] for row in git_active] == ["evt-git-1"]

        # 7. Verify Chrome L2 edge is gone and vec_l2_edges purged, Git L2 edge intact
        chrome_edges = await store.l2.get_relationships(object_id="site:awkward-shop", status_filters=["active"])
        git_edges = await store.l2.get_relationships(object_id="repo:magi", status_filters=["active"])
        assert chrome_edges == []
        assert len(git_edges) == 1
        assert fake_edge_index.delete_entity.await_count >= 1
        purged_ids = [
            call.args[0] if call.args else call.kwargs.get("entity_id")
            for call in fake_edge_index.delete_entity.await_args_list
        ]
        assert chrome_triple_id in purged_ids
        assert git_triple_id not in purged_ids

        # 8. Verify Chrome L3 summary is cleared while Git L3 summary stays intact
        l3_rows = await store.l3.list_summaries(limit=20)
        assert len(l3_rows) == 1
        assert "magi" in l3_rows[0]["content"]

        # 9. Verify Chrome cold archive row deleted while Git cold archive row stays intact
        conn = sqlite3.connect(str(archive_db))
        try:
            remaining_archive_ids = [
                row[0] for row in conn.execute("SELECT event_id FROM archived_l1_events ORDER BY event_id").fetchall()
            ]
        finally:
            conn.close()
        assert remaining_archive_ids == ["evt-git-archived-1"]
    finally:
        await store.shutdown()
