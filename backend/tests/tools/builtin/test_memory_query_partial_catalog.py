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
from unittest.mock import AsyncMock, MagicMock

from magi_plugin_sdk.capabilities import ToolCapabilities


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


def _make_fake_mq_with_db(fake_payload, db_path: str):
    """Build a fake MemoryQueryPort that uses the real get_canonical_names lookup."""

    def _build_query(**kwargs):
        from magi.memory.hybrid_retrieval import build_query
        return build_query(**kwargs)

    def _make_turn(**kwargs):
        from magi.memory.hybrid_retrieval.models import ConversationTurn
        return ConversationTurn(**kwargs)

    def _project(**kwargs):
        from magi.memory.retrieval_projection import project_historical_recall
        return project_historical_recall(**kwargs)

    async def _get_canonical_names(entity_ids):
        from magi.memory.l2.entities.catalog.lookup import get_canonical_names
        return await get_canonical_names(db_path, entity_ids)

    mq = MagicMock(name="memory_query_port")
    mq.build_query.side_effect = _build_query
    mq.query = AsyncMock(return_value=fake_payload)
    mq.get_canonical_names = AsyncMock(side_effect=_get_canonical_names)
    mq.project_historical_recall.side_effect = _project
    mq.make_conversation_turn.side_effect = _make_turn
    return mq


def _make_context(fake_mq, workspace, **kwargs):
    from magi.tools.schema import ToolExecutionContext
    caps = ToolCapabilities(memory_query=fake_mq)
    return ToolExecutionContext(agent_id="a", capabilities=caps, workspace=str(workspace), **kwargs)


@pytest.mark.asyncio
async def test_empty_catalog_still_renders_findings_via_slug_fallback(tmp_path):
    """Fresh deploy: entity_catalog is empty. Phase 5 would have dropped
    everything. Round 4: 'user:local_user' renders as 'local_user',
    'topic:rust' renders as 'rust'. Statement is human-readable."""
    from magi.memory.hybrid_retrieval.models import RetrievalPayload
    from magi.tools.builtin.memory_query_tool import MemoryQueryTool

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
    fake_mq = _make_fake_mq_with_db(fake_payload, db_path)

    result = await tool.execute(
        parameters={"query": "what do I like"},
        context=_make_context(
            fake_mq,
            workspace=tmp_path,
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
    fake_mq = _make_fake_mq_with_db(fake_payload, db_path)

    result = await tool.execute(
        parameters={"query": "what am I interested in"},
        context=_make_context(
            fake_mq,
            workspace=tmp_path,
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
