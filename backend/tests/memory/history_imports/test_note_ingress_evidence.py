"""One note keeps full-body evidence through source sync and Markdown import."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest
from magi_plugin_sdk import ExtractionProfileSpec
from magi_plugin_sdk.sources import SourceMemoryPolicy

from _shared.memory_schema import apply_memory_shared_schema
from _shared.source_event_payloads import make_source_event_payload
from magi.awareness.source_projection import SourceProjection
from magi.memory import MemoryStoreTuning, UnifiedMemoryStore
from magi.memory.history_imports.service import HistoryImportService
from magi.memory.history_imports.store import HistoryImportStore
from magi.memory.source_event_projection import build_source_memory_event
from memory.history_imports.test_history_import_l2_quality import (
    _QualityAdapter,
    _QualityScenarioPool,
    _wait_for_import_and_l2,
)

_TITLE = "# 每周笔记"
_NAME_QUOTE = "我叫明日香，朋友平时也这样称呼我。"
_TOOL_QUOTE = "我平时用 Obsidian 整理自己的笔记。"
_QUOTED_NAME = "我叫苏眠。"
_NOTE = (
    _TITLE
    + "\n\n"
    + "今天整理了一些资料，记录阅读过程。\n" * 40
    + f"\n> {_QUOTED_NAME}\n\n{_TOOL_QUOTE}\n\n{_NAME_QUOTE}"
)


def _local_note_profile() -> list[ExtractionProfileSpec]:
    # Keep the external local-documents contract restrictive in this host test.
    return [
        ExtractionProfileSpec(
            profile_id="source.local_documents",
            source_types=["local_documents"],
            allowed_entity_types=[
                "concept",
                "topic",
                "person",
                "project",
                "software",
                "organization",
                "product",
                "technology",
                "media",
            ],
            allowed_predicates=[
                "REFERENCES",
                "INTERESTED_IN",
                "KNOWS",
                "USES",
                "WORKS_WITH",
                "MEMBER_OF",
            ],
            structured_allowed_entity_types=["concept", "topic"],
            structured_allowed_predicates=["REFERENCES"],
            allow_graph=True,
            allow_assertion=False,
        )
    ]


def _extraction_payload() -> dict[str, object]:
    claims = []
    for predicate, value, object_type, quote in [
        ("REAL_NAME", "明日香", "person", _NAME_QUOTE),
        ("USES", "software:obsidian", "software", _TOOL_QUOTE),
        ("REAL_NAME", "苏眠", "person", _QUOTED_NAME),
        ("REAL_NAME", "不存在", "person", "我叫不存在。"),
    ]:
        claims.append(
            {
                "assertion_mode": "asserted",
                "subject_ref": "user:self",
                "subject_type": "user",
                "predicate": predicate,
                "object_ref": value,
                "object_type": object_type,
                "fact_kind": "explicit_fact",
                "temporal_cue": "unspecified",
                "polarity": "positive",
                "specificity": "concrete",
                "evidence_text": quote,
                "confidence": 0.99,
            }
        )
    return {
        "entities": [
            {
                "referent_kind": "entity",
                "surface": "Obsidian",
                "normalized_name": "Obsidian",
                "entity_type": "software",
                "specificity": "concrete",
                "resolved_id": "software:obsidian",
                "is_new": False,
                "alias_signals": [],
                "confidence": 0.99,
            }
        ],
        "fact_claims": claims,
        "resolved_refs": [],
        "diagnostics": {"entity_status": "found"},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("ingress", ["source_sync", "markdown_import"])
async def test_same_note_uses_full_body_for_prompt_claims_and_persisted_locators(
    tmp_path: Path,
    ingress: str,
) -> None:
    note_path = tmp_path / "每周笔记.md"
    note_path.write_text(_NOTE, encoding="utf-8")
    memory_db = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(memory_db)
    adapter = _QualityAdapter(_extraction_payload())
    memory = UnifiedMemoryStore(
        persist_dir=str(tmp_path / "memory"),
        l1_db_path=str(tmp_path / "l1.db"),
        memory_db_path=memory_db,
        archive_dir_path=str(tmp_path / "archive"),
        enable_l0=False,
        enable_l3=False,
        enable_l4=False,
        l2_batch_flush_interval_seconds=0,
        scenario_llm_pool=_QualityScenarioPool(adapter),
        extraction_profile_provider=_local_note_profile,
        tuning=MemoryStoreTuning(
            enable_l1_vectors=False,
            enable_l2_vectors=False,
            enable_l3_vectors=False,
            enable_l4_vectors=False,
            enable_l3_llm_summary=False,
            async_embeddings=False,
        ),
    )
    service = None
    await memory.initialize()
    try:
        assert memory.l1 is not None and memory.l2 is not None
        assert memory.l2_entity_catalog is not None
        await memory.l2_entity_catalog.upsert_entity(
            entity_id="software:obsidian",
            canonical_name="Obsidian",
            entity_type="software",
        )
        if ingress == "markdown_import":
            service = HistoryImportService(
                store=HistoryImportStore(db_path=memory_db), memory=memory
            )
            preview = await service.preview_markdown_paths([str(note_path)])
            assert preview.preview_records[0].content == _NOTE
            await service.confirm(
                job_id=preview.job_id,
                confirm_personal_writing=True,
                included_source_ids=preview.included_source_ids,
            )
            await _wait_for_import_and_l2(service, memory, job_id=preview.job_id)
        else:
            output = {
                "source_type": "local_documents",
                "source_item_id": "weekly-note",
                "occurred_at": 1_790_000_000.0,
                "captured_at": 1_790_000_001.0,
                "domain_payload": {"path": str(note_path)},
                "pinned_payload": _NOTE,
                "raw_payload_ref": None,
                "provenance": {},
                "tags": [],
                "entities": [],
                "content_blocks": [],
            }
            payload = make_source_event_payload(
                source_name="local_documents",
                source_id="local_documents",
                owner_user_id="local_user",
                output_dict=output,
                payload=dict(output),
                metadata_dict={},
                policy_dict=SourceMemoryPolicy(
                    memory_domain="user_authored",
                    ingest_target="l1_only",
                    cognition_eligible=True,
                    retention_class="permanent",
                    importance_bias=0.6,
                    author_type="user",
                    content_type="text",
                ).to_dict(),
                projection_dict=SourceProjection(
                    title=_TITLE,
                    summary=_TITLE,
                    content=_TITLE,
                    embedding_head=_TITLE,
                    metadata={},
                ).to_dict(),
                idempotency_key="source:weekly-note:v1",
            )
            event = build_source_memory_event(payload, event_id="evt-note")
            receipt = await memory.ingest_event(event)
            assert receipt["l2_job_enqueued"] is True
            # Extraction owns the captured payload, even if the live file changes.
            note_path.write_text("The live note has changed.", encoding="utf-8")
            for _ in range(500):
                stats = memory.get_l2_pipeline_stats()
                assert stats["extract_failed"] == 0, stats
                if stats["extract_completed"] >= 1:
                    break
                await asyncio.sleep(0.01)
            else:
                pytest.fail("Source note did not complete L2 extraction")

        for prose in _NOTE.split("> 我叫苏眠。"):
            assert prose.strip() in adapter.calls[0]["prompt"]
        assert "> 我叫苏眠。" not in adapter.calls[0]["prompt"]
        raw_events = await memory.l1.query_events()
        assert len(raw_events) == 1
        raw = raw_events[0]
        assert raw["content"] == (_TITLE if ingress == "source_sync" else _NOTE)
        pinned = await memory.l1.get_pinned_payloads([raw["event_id"]])
        assert pinned == ({raw["event_id"]: _NOTE} if ingress == "source_sync" else {})
        mentions = await memory.l2_entity_catalog.list_mentions(limit=10)
        obsidian_mentions = [row for row in mentions if row["mention_text"] == "Obsidian"]
        assert len(obsidian_mentions) == 1
        assert obsidian_mentions[0]["evidence_event_ids"] == [raw["event_id"]]
        claims = await memory.l2.list_grounded_claims(user_id="local_user")
        assert {row["canonical_predicate"] for row in claims} == {"REAL_NAME", "USES"}
        assert len(claims) == 2
        for claim in claims:
            quote = _NAME_QUOTE if claim["canonical_predicate"] == "REAL_NAME" else _TOOL_QUOTE
            stored = await memory.l2.get_grounded_claim(claim["claim_id"])
            assert stored is not None and len(stored["evidence"]) == 1
            evidence = stored["evidence"][0]
            assert evidence["event_id"] == raw["event_id"]
            assert evidence["author_type"] == "user"
            locator = evidence["evidence_locator"]
            assert (locator["start"], locator["end"]) == (
                _NOTE.index(quote),
                _NOTE.index(quote) + len(quote),
            )
            assert _NOTE[locator["start"] : locator["end"]] == quote
            assert locator["quote_hash"] == hashlib.sha256(quote.encode()).hexdigest()
            assert locator["content_hash"] == hashlib.sha256(_NOTE.encode()).hexdigest()
            assert locator["content_source"] == (
                "pinned_payload" if ingress == "source_sync" else "event_content"
            )
        assertions = await memory.l2.list_current_assertions(
            entity_id="user:local_user", committed_only=False
        )
        if ingress == "source_sync":
            assert assertions == []
        else:
            assert any(row["trait_name"] == "identity.real_name" for row in assertions)
    finally:
        if service is not None:
            await service.stop()
        await memory.shutdown()
