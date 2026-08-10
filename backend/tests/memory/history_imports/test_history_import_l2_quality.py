"""End-to-end quality baseline for personal Markdown history imports."""

from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from _shared.memory_schema import apply_memory_shared_schema
from magi.memory import MemoryStoreTuning, UnifiedMemoryStore
from magi.memory.history_imports import service as history_import_service_module
from magi.memory.history_imports.service import (
    HISTORY_IMPORT_SOURCE,
    HistoryImportService,
)
from magi.memory.history_imports.store import HistoryImportStore


class _QualityAdapter:
    def __init__(self, phase1_payload: dict[str, object]) -> None:
        self._phase1_payload = phase1_payload
        self.calls: list[dict[str, object]] = []
        self.provider_name = "openai"
        self.model_name = "history-import-quality-test"
        self._client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=self._create_completion),
            )
        )

    async def _create_completion(self, **kwargs):  # type: ignore[no-untyped-def]
        messages = kwargs.get("messages") or []
        system_prompt = str(kwargs.get("system_prompt") or "")
        prompt = ""
        if isinstance(messages, list):
            if not system_prompt and messages and isinstance(messages[0], dict):
                system_prompt = str(messages[0].get("content") or "")
            if len(messages) > 1 and isinstance(messages[1], dict):
                prompt = str(messages[1].get("content") or "")
            elif len(messages) == 1 and isinstance(messages[0], dict):
                prompt = str(messages[0].get("content") or "")
        self.calls.append({"prompt": prompt, "system_prompt": system_prompt})
        if len(self.calls) == 1:
            event_ids = re.findall(r"\bhi_[0-9a-f]{32}\b", prompt)
            assert len(set(event_ids)) == 1
            payload = json.loads(json.dumps(self._phase1_payload, ensure_ascii=False))
            for claim in payload["fact_claims"]:
                claim["supporting_event_ids"] = [event_ids[0]]
            response_text = json.dumps(payload, ensure_ascii=False)
        else:
            response_text = json.dumps({"summaries": []})
        message = SimpleNamespace(content=response_text, tool_calls=[], role="assistant")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message, finish_reason="stop")],
            usage=None,
        )


class _QualityScenarioPool:
    def __init__(self, adapter: _QualityAdapter) -> None:
        self._adapter = adapter

    def get(self, scenario):  # type: ignore[no-untyped-def]
        return self._adapter


async def _wait_for_import_and_l2(
    service: HistoryImportService,
    memory: UnifiedMemoryStore,
    *,
    job_id: str,
) -> None:
    for _ in range(500):
        job = await service.get_job(job_id)
        stats = memory.get_l2_pipeline_stats()
        if job.status == "completed" and stats["extract_completed"] >= 1:
            return
        if stats["extract_failed"]:
            pytest.fail("L2 extraction failed for the imported Markdown fixture")
        await asyncio.sleep(0.01)
    pytest.fail("Markdown import did not reach completed L2 extraction")


@pytest.mark.asyncio
async def test_personal_markdown_reaches_l1_and_governed_l2_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        history_import_service_module,
        "local_calendar_timezone_id",
        lambda: "Asia/Shanghai",
    )
    markdown = tmp_path / "七月近况.md"
    markdown.write_text(
        "---\ndate: 2026-07-20\n---\n\n"
        "# 七月近况\n\n"
        "我叫明日香，朋友平时也这样称呼我。\n\n"
        "我一直很喜欢 DIIV，最近又把《Oshin》听了几遍。\n\n"
        "今天第一次在陌生街区闲逛，最喜欢的是随便找早餐店的过程。\n\n"
        "我计划 2099 年秋天去一次海边。\n",
        encoding="utf-8",
    )
    phase1_payload: dict[str, object] = {
        "entities": [
            {
                "surface": "DIIV",
                "normalized_name": "DIIV",
                "entity_type": "group",
                "specificity": "concrete",
                "resolved_id": "group:diiv",
                "is_new": False,
                "alias_signals": [],
                "confidence": 0.99,
            }
        ],
        "fact_claims": [
            {
                "subject_ref": "user:self",
                "subject_type": "user",
                "predicate": "REAL_NAME",
                "object_ref": "明日香",
                "object_type": "person",
                "fact_kind": "explicit_fact",
                "temporal_cue": "unspecified",
                "polarity": "positive",
                "specificity": "concrete",
                "evidence_text": "我叫明日香，朋友平时也这样称呼我。",
                "confidence": 0.99,
            },
            {
                "subject_ref": "user:self",
                "subject_type": "user",
                "predicate": "LIKES",
                "object_ref": "group:diiv",
                "object_type": "group",
                "fact_kind": "stable_preference",
                "temporal_cue": "stable",
                "polarity": "positive",
                "specificity": "concrete",
                "evidence_text": "我一直很喜欢 DIIV，最近又把《Oshin》听了几遍。",
                "confidence": 0.98,
            },
            {
                "subject_ref": "user:self",
                "subject_type": "user",
                "predicate": "LIKES",
                "object_ref": "随便找早餐店的过程",
                "object_type": "activity",
                "fact_kind": "explicit_fact",
                "temporal_cue": "one_off",
                "polarity": "positive",
                "specificity": "concrete",
                "evidence_text": ("今天第一次在陌生街区闲逛，最喜欢的是随便找早餐店的过程。"),
                "confidence": 0.92,
            },
            {
                "subject_ref": "user:self",
                "subject_type": "user",
                "predicate": "PLANS_TO",
                "object_ref": "2099 年秋天去一次海边",
                "object_type": "activity",
                "fact_kind": "future_intent",
                "temporal_cue": "one_off",
                "raw_time_expression": "2099 年秋天",
                "polarity": "positive",
                "specificity": "concrete",
                "evidence_text": "我计划 2099 年秋天去一次海边。",
                "confidence": 0.96,
            },
        ],
        "resolved_refs": [],
        "diagnostics": {"entity_status": "found"},
    }
    memory_db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(memory_db_path)
    adapter = _QualityAdapter(phase1_payload)
    memory = UnifiedMemoryStore(
        persist_dir=str(tmp_path / "memory"),
        l1_db_path=str(tmp_path / "l1.db"),
        memory_db_path=memory_db_path,
        archive_dir_path=str(tmp_path / "archive"),
        enable_l0=False,
        enable_l3=False,
        enable_l4=False,
        l2_batch_flush_interval_seconds=0,
        scenario_llm_pool=_QualityScenarioPool(adapter),
        tuning=MemoryStoreTuning(
            enable_l1_vectors=False,
            enable_l2_vectors=False,
            enable_l3_vectors=False,
            enable_l4_vectors=False,
            enable_l3_llm_summary=False,
            async_embeddings=False,
        ),
    )
    service: HistoryImportService | None = None
    await memory.initialize()
    try:
        assert memory.l1 is not None
        assert memory.l2 is not None
        assert memory.l2_entity_catalog is not None
        await memory.l2_entity_catalog.upsert_entity(
            entity_id="group:diiv",
            canonical_name="DIIV",
            entity_type="group",
        )
        service = HistoryImportService(
            store=HistoryImportStore(db_path=memory_db_path),
            memory=memory,
        )
        preview = await service.preview_markdown_paths([str(markdown)])
        expected_content = preview.preview_records[0].content
        confirmed = await service.confirm(
            job_id=preview.job_id,
            confirm_personal_writing=True,
            included_files=preview.included_files,
        )
        assert confirmed.quick_ready is True
        await _wait_for_import_and_l2(service, memory, job_id=preview.job_id)

        l1_events = await memory.l1.query_events(
            source_filters=[HISTORY_IMPORT_SOURCE],
            order_by="timestamp_asc",
        )
        claims = await memory.l2.list_grounded_claims(user_id="local_user")
        assertions = await memory.l2.list_current_assertions(
            entity_id="user:local_user",
            committed_only=False,
        )
        relationships = await memory.l2.list_current_relationships(
            subject_id="user:local_user",
            committed_only=False,
        )
        pending_reviews = await memory.l2.list_pending_reviews(subject_id="user:local_user")

        assert len(l1_events) == 1
        assert l1_events[0]["content"] == expected_content
        assert not l1_events[0]["content"].startswith("---")
        assert l1_events[0]["event_type"] == "history_import.document"
        assert Counter(claim["canonical_predicate"] for claim in claims) == Counter(
            {"REAL_NAME": 1, "LIKES": 2, "PLANS_TO": 1}
        )
        assert Counter(row["trait_name"] for row in assertions) == Counter(
            {
                "identity.real_name": 1,
                "preference.affinity": 1,
            }
        )
        assert len(pending_reviews) == 1
        assert pending_reviews[0]["kind"] == "goal_currentness"
        assert [row["predicate"] for row in relationships] == ["LIKES"]
        assert relationships[0]["object_id"] == "group:diiv"
        assert relationships[0]["evidence_event_ids"] == [l1_events[0]["event_id"]]
        assert all(row["predicate"] != "PLANS_TO" for row in relationships)
    finally:
        if service is not None:
            await service.stop()
        await memory.shutdown()
