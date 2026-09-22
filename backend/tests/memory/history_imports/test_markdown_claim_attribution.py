"""Imported prose uses semantic attribution after structural source validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from _shared.memory_schema import apply_memory_shared_schema
from magi.memory import MemoryStoreTuning, UnifiedMemoryStore
from magi.memory.history_imports.service import HistoryImportService
from magi.memory.history_imports.store import HistoryImportStore
from magi.user_profile.portrait_projection_builder import UserPortraitProjectionBuilder
from memory.l2.test_claim_text_pipeline import _response
from memory.l2.test_phase1_entity_grounding import _entity
from memory.history_imports.test_history_import_l2_quality import _QualityAdapter, _QualityScenarioPool, _wait_for_import_and_l2


@pytest.mark.asyncio
@pytest.mark.parametrize(("content", "evidence", "assertion_mode", "kept"), [
    ("爱好：我一直很喜欢 DIIV。", "我一直很喜欢 DIIV。", "asserted", 1),
    ("音乐口味：我一直很喜欢 DIIV。", "我一直很喜欢 DIIV。", "asserted", 1),
    ("Hobbies: 我一直很喜欢 DIIV。", "我一直很喜欢 DIIV。", "asserted", 1),
    ("**个人兴趣：** DIIV 一直是我最爱的乐队。", "DIIV 一直是我最爱的乐队。", "asserted", 1),
    ("Alice: 我一直很喜欢 DIIV。", "我一直很喜欢 DIIV。", "quoted", 0),
    ('她的想法是“我一直很喜欢 DIIV。”', "我一直很喜欢 DIIV。", "quoted", 0),
    ("user: 我一直很喜欢 DIIV。", "我一直很喜欢 DIIV。", "asserted", 0),
    ("> 我一直很喜欢 DIIV。", "我一直很喜欢 DIIV。", "asserted", 0),
    ("```text\n我一直很喜欢 DIIV。\n```", "我一直很喜欢 DIIV。", "asserted", 0),
])
async def test_imported_document_preserves_prose_and_rejects_non_author_claims(
    tmp_path: Path, content: str, evidence: str, assertion_mode: str, kept: int,
) -> None:
    markdown = tmp_path / "Personal notes.md"
    markdown.write_text(content, encoding="utf-8")
    payload = json.loads(_response(
        event_id="current", object_ref="group:diiv", evidence=evidence,
        entities=[_entity("DIIV", "DIIV", "group", resolved_id="group:diiv")],
        object_type="group", temporal_cue="stable",
    ))
    payload["fact_claims"][0]["assertion_mode"] = assertion_mode
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    adapter = _QualityAdapter(payload)
    memory = UnifiedMemoryStore(
        persist_dir=str(tmp_path / "memory"), l1_db_path=str(tmp_path / "l1.db"),
        memory_db_path=db_path, archive_dir_path=str(tmp_path / "archive"),
        enable_l0=False, enable_l3=False, enable_l4=False,
        l2_batch_flush_interval_seconds=0, scenario_llm_pool=_QualityScenarioPool(adapter),
        tuning=MemoryStoreTuning(
            enable_l1_vectors=False, enable_l2_vectors=False, enable_l3_vectors=False,
            enable_l4_vectors=False, enable_l3_llm_summary=False, async_embeddings=False,
        ),
    )
    service = None
    await memory.initialize()
    try:
        await memory.l2_entity_catalog.upsert_entity(
            entity_id="group:diiv", canonical_name="DIIV", entity_type="group",
        )
        service = HistoryImportService(store=HistoryImportStore(db_path=db_path), memory=memory)
        preview = await service.preview_markdown_paths([str(markdown)])
        await service.confirm(
            job_id=preview.job_id, confirm_personal_writing=True,
            included_source_ids=preview.included_source_ids,
        )
        await _wait_for_import_and_l2(service, memory, job_id=preview.job_id)
        claims = await memory.l2.list_grounded_claims(user_id="local_user")
        assert len(claims) == kept
        portrait = await UserPortraitProjectionBuilder(memory.l2).build("local_user")
        if kept:
            assert claims[0]["object_surface"] == "DIIV"
            assert any("DIIV" in line for line in portrait.prompt_summary)
        else:
            assert await memory.l2.list_current_assertions(entity_id="user:local_user") == []
            assert await memory.l2.list_current_relationships(subject_id="user:local_user") == []
            assert portrait.prompt_summary == []
        assert len(adapter.calls) == 1
    finally:
        if service is not None:
            await service.stop()
        await memory.shutdown()
