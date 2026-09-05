"""End-to-end integration test for Phase 5 canonical-name resolution.

Verifies the real flow:
  memory_query_tool.execute()
   -> mq.query() (mocked via port)
   -> executor collects entity_ids from ALL payload surfaces
   -> mq.get_canonical_names() against real seeded entity_catalog
   -> mq.project_historical_recall() with the resolved dict
   -> envelope rendered without raw entity_ids

This was missing from Phase 5 -- all Phase 5 tests pass canonical_names
directly into project_historical_recall, bypassing the executor's id-
collection logic. Round 3 added this test along with the C1 fix that
makes it pass (executor now also collects entity_card + resolved_entities ids).
"""

from __future__ import annotations

import aiosqlite
import pytest
from unittest.mock import AsyncMock, MagicMock

from magi_plugin_sdk.capabilities import ToolCapabilities


async def _seed_entity_catalog(db_path: str, rows: list[tuple[str, str]]) -> None:
    """Seed entity_catalog with (entity_id, canonical_name) rows."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS entity_catalog ("
            " entity_id TEXT PRIMARY KEY, canonical_name TEXT)"
        )
        await db.executemany(
            "INSERT INTO entity_catalog (entity_id, canonical_name) VALUES (?, ?)",
            rows,
        )
        await db.commit()


def _make_fake_mq_with_real_db(fake_payload, db_path: str):
    """Build a fake MemoryQueryPort that routes get_canonical_names to the real DB."""

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
    return ToolExecutionContext(agent_id="agent-1", capabilities=caps, workspace=str(workspace), **kwargs)


@pytest.mark.asyncio
async def test_e2e_entity_card_entity_id_resolved_via_real_catalog(tmp_path):
    """C1 north star: when payload has l2_entity_cards referencing
    entity_id='74f953b57f75', and the real entity_catalog has the canonical
    name, the executor must collect that entity_id and the envelope's
    entity_refs must render with the canonical name (not the raw hash)."""
    from magi.memory.hybrid_retrieval.models import RetrievalPayload
    from magi.tools.builtin.memory_query_tool import MemoryQueryTool

    # Seed a real (file-backed) entity_catalog DB
    db_path = str(tmp_path / "memory.sqlite")
    await _seed_entity_catalog(
        db_path,
        [
            ("user:local_user", "asuka"),
            ("74f953b57f75", "字节跳动"),
        ],
    )

    tool = MemoryQueryTool()
    # Mock the retrieval service to return a payload referencing those entities
    # via l2_entity_cards. The CRITICAL property: the entity_ids ONLY appear
    # in l2_entity_cards (not relationships/assertions), so the executor MUST
    # collect from that surface for the leak fix to work.
    fake_payload = RetrievalPayload(
        l2_entity_cards=[
            {"entity_id": "74f953b57f75", "entity_type": "organization"},
            {"entity_id": "user:local_user", "entity_type": "person"},
        ],
    )
    fake_mq = _make_fake_mq_with_real_db(fake_payload, db_path)

    result = await tool.execute(
        parameters={"query": "who am I interested in"},
        context=_make_context(
            fake_mq,
            workspace=tmp_path,
            env_vars={"user_id": "u1", "session_id": ""},
            permissions=[],
        ),
    )

    assert result.success is True
    envelope = result.data["historical_recall"]
    entity_refs = envelope.get("entity_refs") or []

    # The CRITICAL assertion: entity_refs must NOT be empty
    # (would be empty if C1 collection gap exists)
    assert len(entity_refs) > 0, (
        "entity_refs should be populated when l2_entity_cards reference "
        "resolvable entity_ids; got empty list -- C1 collection gap present"
    )

    # The hash-leak bug class: canonical_name MUST be present (not the hash)
    # for the org card. entity_id is preserved as a stable identifier — the
    # bug Phase 5 closed was the hash being rendered as a DISPLAY LABEL.
    org_ref = next(
        (r for r in entity_refs if r.get("entity_id") == "74f953b57f75"),
        None,
    )
    assert org_ref is not None, (
        f"entity_card for org id was dropped despite catalog resolution; "
        f"refs={entity_refs}"
    )
    assert org_ref.get("canonical_name") == "字节跳动", (
        f"expected canonical_name='字节跳动'; got {org_ref!r} -- C1 "
        "collection gap meant id never reached the resolver"
    )

    # Canonical name appears in the envelope's display surface
    import json
    envelope_json = json.dumps(envelope, default=str, ensure_ascii=False)
    assert "字节跳动" in envelope_json, (
        f"canonical name '字节跳动' missing from envelope:\n{envelope_json[:500]}"
    )


@pytest.mark.asyncio
async def test_e2e_unresolved_entity_card_is_dropped_not_leaked(tmp_path):
    """When l2_entity_cards reference entity_ids NOT in the catalog, the
    ref must be dropped -- never rendered with the raw hash."""
    from magi.memory.hybrid_retrieval.models import RetrievalPayload
    from magi.tools.builtin.memory_query_tool import MemoryQueryTool

    db_path = str(tmp_path / "memory.sqlite")
    # Catalog is empty / missing the referenced entity
    await _seed_entity_catalog(db_path, [("user:local_user", "asuka")])

    tool = MemoryQueryTool()
    fake_payload = RetrievalPayload(
        l2_entity_cards=[
            {"entity_id": "abc123def456", "entity_type": "organization"},
            # unresolvable hash
        ],
    )
    fake_mq = _make_fake_mq_with_real_db(fake_payload, db_path)

    result = await tool.execute(
        parameters={"query": "test"},
        context=_make_context(
            fake_mq,
            workspace=tmp_path,
            env_vars={"user_id": "u1", "session_id": ""},
            permissions=[],
        ),
    )

    assert result.success is True
    envelope = result.data["historical_recall"]
    # When the catalog has no entry for an entity_card id, the ref must be
    # dropped entirely (not rendered with the hash as the canonical_name).
    entity_refs = envelope.get("entity_refs") or []
    leaking = [r for r in entity_refs if r.get("entity_id") == "abc123def456"]
    assert leaking == [], (
        f"unresolved entity_card ref must be dropped, not rendered with raw "
        f"hash; got {leaking}"
    )
    # And the hash must not leak into any display field (canonical_name,
    # statement, summary, etc.).
    import json
    for ref in entity_refs:
        for field in ("canonical_name", "name", "label", "display_name"):
            value = ref.get(field)
            if value is not None:
                assert "abc123def456" not in str(value), (
                    f"hash leaked into entity_ref display field {field}: {ref}"
                )
    findings_json = json.dumps(envelope.get("findings") or [], default=str)
    assert "abc123def456" not in findings_json, (
        f"hash leaked into findings:\n{findings_json[:500]}"
    )
