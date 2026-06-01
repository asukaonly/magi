"""End-to-end test for Round 4 (C2): partial entity_catalog still produces
useful findings via entity_display fallback.

Phase 5's drop-unresolvable policy hit a regression where fresh/partial
deployments saw 'no memory found' even when KG had data. Round 4's
entity_display helper provides slug-based + (未命名 {type}) fallbacks so
the user sees actual content in those cases."""

from __future__ import annotations

import json

import aiosqlite
import pytest
from unittest.mock import AsyncMock, patch


async def _seed_entity_catalog(db_path: str, rows: list[tuple[str, str]]) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS entity_catalog ("
            " entity_id TEXT PRIMARY KEY, canonical_name TEXT)"
        )
        if rows:
            await db.executemany(
                "INSERT INTO entity_catalog (entity_id, canonical_name) VALUES (?, ?)",
                rows,
            )
        await db.commit()


@pytest.mark.asyncio
async def test_empty_catalog_still_renders_findings_via_slug_fallback(tmp_path):
    """Fresh deploy: entity_catalog is empty. Phase 5 would have dropped
    everything. Round 4: 'user:local_user' renders as 'local_user',
    'topic:rust' renders as 'rust'. Statement is human-readable."""
    from magi.memory.hybrid_retrieval.models import RetrievalPayload
    from magi.tools.builtin.memory_query_tool import MemoryQueryTool
    from magi.tools.schema import ToolExecutionContext

    db_path = str(tmp_path / "memory.sqlite")
    await _seed_entity_catalog(db_path, [])  # empty

    tool = MemoryQueryTool()
    fake_payload = RetrievalPayload(
        l2_relationships=[
            {
                "subject_id": "user:local_user",
                "predicate": "LIKES",
                "object_id": "topic:rust",
                "confidence": 0.9,
                "status": "active",
            }
        ],
    )
    fake_service = AsyncMock()
    fake_service.query = AsyncMock(return_value=fake_payload)
    fake_service.memory_db_path = db_path

    with patch.object(tool, "_get_service", return_value=fake_service):
        result = await tool.execute(
            parameters={"query": "what do I like"},
            context=ToolExecutionContext(
                agent_id="a", workspace=str(tmp_path),
                env_vars={"user_id": "u1", "session_id": ""},
                permissions=[],
            ),
        )

    assert result.success is True
    envelope = result.data["historical_recall"]
    findings = envelope.get("findings") or []
    assert len(findings) > 0, "empty catalog must NOT drop slug-resolvable findings"
    stmt = findings[0]["statement"]
    assert "local_user" in stmt
    assert "rust" in stmt
    assert "user:local_user" not in stmt  # raw id not in display
    assert "topic:rust" not in stmt


@pytest.mark.asyncio
async def test_empty_catalog_hash_object_renders_unnamed(tmp_path):
    """Fresh deploy: object_id is a pure hash (organization:74f953...).
    Round 4: rendered as '(未命名 organization)', not dropped, no hash leak."""
    from magi.memory.hybrid_retrieval.models import RetrievalPayload
    from magi.tools.builtin.memory_query_tool import MemoryQueryTool
    from magi.tools.schema import ToolExecutionContext

    db_path = str(tmp_path / "memory.sqlite")
    await _seed_entity_catalog(db_path, [])

    tool = MemoryQueryTool()
    fake_payload = RetrievalPayload(
        l2_relationships=[
            {
                "subject_id": "user:local_user",
                "predicate": "INTERESTED_IN",
                "object_id": "organization:74f953b57f75",
                "confidence": 0.9,
                "status": "active",
            }
        ],
    )
    fake_service = AsyncMock()
    fake_service.query = AsyncMock(return_value=fake_payload)
    fake_service.memory_db_path = db_path

    with patch.object(tool, "_get_service", return_value=fake_service):
        result = await tool.execute(
            parameters={"query": "what am I interested in"},
            context=ToolExecutionContext(
                agent_id="a", workspace=str(tmp_path),
                env_vars={"user_id": "u1", "session_id": ""},
                permissions=[],
            ),
        )

    assert result.success is True
    envelope = result.data["historical_recall"]
    envelope_str = json.dumps(envelope, default=str, ensure_ascii=False)

    findings = envelope.get("findings") or []
    assert len(findings) > 0
    stmt = findings[0]["statement"]
    assert "local_user" in stmt
    assert "(未命名 organization)" in stmt
    assert "74f953b57f75" not in envelope_str  # safety invariant: no hash anywhere
