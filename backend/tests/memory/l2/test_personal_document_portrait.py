"""Document self-reports traverse the real Claim, assertion and portrait pipeline."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
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
from magi.memory.manual_entries import (
    ManualEntry,
    ManualEntryL1Projector,
    ManualEntryStore,
    ManualEntryWorkflow,
)
from magi.memory.source_event_projection import build_source_memory_event
from magi.user_profile.portrait_projection_builder import UserPortraitProjectionBuilder
from memory.history_imports.test_history_import_l2_quality import (
    _QualityAdapter,
    _QualityScenarioPool,
    _wait_for_import_and_l2,
)
from memory.l2.test_claim_text_pipeline import _open_store, _response
from memory.manual_entries.test_evidence import _doc

_NAME = "我叫明日香。"
_ADDRESS = "请叫我小明。"
_LIKES = "我一直喜欢 DIIV。"
_DISLIKES = "我一直不喜欢咖啡。"
_PLAN = "我计划 2099 年秋天去海边。"
_NOTE = (
    "# 近况\n\n"
    + "今天整理了读书资料。\n" * 40
    + f"\n> {_NAME}\n\n> 我叫苏眠。\n\n{_NAME}\n\n{_ADDRESS}\n\n{_LIKES}\n\n{_DISLIKES}\n\n{_PLAN}\n\n"
    + "Alice 告诉我，她叫艾琳。\n\n转录 Alice 的原话：我喜欢爵士乐。\n\n"
    + "如果有时间，我会开始画画。\n\n我可能喜欢游泳。\n"
)


def _profiles():
    return [
        ExtractionProfileSpec(
            profile_id=f"source.{source}",
            source_types=[source],
            allowed_entity_types="all",
            allowed_predicates="all",
            allow_assertion=True,
            structured_allowed_entity_types=["concept", "topic"],
            structured_allowed_predicates=["REFERENCES"],
        )
        for source in ["local_documents", "obsidian_vault"]
    ]


def _payload():
    claims = []
    for predicate, value, object_type, quote, kind, mode, subject, polarity, cue in [
        (
            "REAL_NAME",
            "明日香",
            "person",
            _NAME,
            "explicit_fact",
            "asserted",
            "user:self",
            "positive",
            "unspecified",
        ),
        (
            "PREFERRED_FORM_OF_ADDRESS",
            "小明",
            "other",
            _ADDRESS,
            "explicit_fact",
            "asserted",
            "user:self",
            "positive",
            "unspecified",
        ),
        (
            "LIKES",
            "group:diiv",
            "group",
            _LIKES,
            "stable_preference",
            "asserted",
            "user:self",
            "positive",
            "stable",
        ),
        (
            "LIKES",
            "food:coffee",
            "food",
            _DISLIKES,
            "stable_preference",
            "asserted",
            "user:self",
            "negative",
            "stable",
        ),
        (
            "PLANS_TO",
            "2099 年秋天去海边",
            "activity",
            _PLAN,
            "future_intent",
            "asserted",
            "user:self",
            "positive",
            "one_off",
        ),
        (
            "REAL_NAME",
            "苏眠",
            "person",
            "我叫苏眠。",
            "explicit_fact",
            "asserted",
            "user:self",
            "positive",
            "unspecified",
        ),
        (
            "REAL_NAME",
            "艾琳",
            "person",
            "Alice 告诉我，她叫艾琳。",
            "explicit_fact",
            "asserted",
            "person:alice",
            "positive",
            "unspecified",
        ),
        (
            "LIKES",
            "爵士乐",
            "concept",
            "我喜欢爵士乐。",
            "stable_preference",
            "quoted",
            "user:self",
            "positive",
            "stable",
        ),
        (
            "PLANS_TO",
            "画画",
            "activity",
            "如果有时间，我会开始画画。",
            "future_intent",
            "conditional",
            "user:self",
            "positive",
            "unspecified",
        ),
        (
            "LIKES",
            "游泳",
            "activity",
            "我可能喜欢游泳。",
            "stable_preference",
            "uncertain",
            "user:self",
            "positive",
            "unspecified",
        ),
    ]:
        claims.append(
            dict(
                assertion_mode=mode,
                subject_ref=subject,
                subject_type="user" if subject == "user:self" else "person",
                predicate=predicate,
                object_ref=value,
                object_type=object_type,
                fact_kind=kind,
                temporal_cue=cue,
                polarity=polarity,
                specificity="concrete",
                evidence_text=quote,
                confidence=0.99,
                raw_time_expression="2099 年秋天" if quote == _PLAN else "",
            )
        )
    entities = [
        dict(
            referent_kind="entity",
            surface=name,
            normalized_name=name,
            entity_type=kind,
            specificity="concrete",
            resolved_id=ref,
            is_new=False,
            alias_signals=[],
            confidence=0.99,
        )
        for name, kind, ref in [
            ("DIIV", "group", "group:diiv"),
            ("咖啡", "food", "food:coffee"),
            ("Alice", "person", "person:alice"),
        ]
    ]
    return dict(
        entities=entities,
        fact_claims=claims,
        resolved_refs=[],
        diagnostics={"entity_status": "found"},
    )


def _source_event(source: str, content: str, *, cognition: bool = True):
    output = dict(
        source_type=source,
        source_item_id="note",
        occurred_at=1_790_000_000.0,
        captured_at=1_790_000_001.0,
        domain_payload={},
        pinned_payload=content,
        raw_payload_ref=None,
        provenance={},
        tags=[],
        entities=[],
        content_blocks=[],
    )
    payload = make_source_event_payload(
        source_name=source,
        source_id=source,
        owner_user_id="local_user",
        output_dict=output,
        payload=dict(output),
        metadata_dict={},
        policy_dict=SourceMemoryPolicy(
            memory_domain="user_authored",
            ingest_target="l1_only",
            cognition_eligible=cognition,
            retention_class="permanent",
            importance_bias=0.6,
            author_type="user",
            content_type="text",
        ).to_dict(),
        projection_dict=SourceProjection(
            title="近况", summary="近况", content="近况", embedding_head="近况", metadata={}
        ).to_dict(),
        idempotency_key=f"{source}:note:v1",
    )
    return build_source_memory_event(payload, event_id="evt-note")


async def _wait(memory, completed=1):
    for _ in range(500):
        stats = memory.get_l2_pipeline_stats()
        assert stats["extract_failed"] == 0, stats
        if stats["extract_completed"] >= completed:
            return
        await asyncio.sleep(0.01)
    pytest.fail("Document extraction did not complete")


async def _memory(tmp_path: Path, adapter):
    memory_db = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(memory_db)
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
        extraction_profile_provider=_profiles,
        tuning=MemoryStoreTuning(
            enable_l1_vectors=False,
            enable_l2_vectors=False,
            enable_l3_vectors=False,
            enable_l4_vectors=False,
            enable_l3_llm_summary=False,
            async_embeddings=False,
        ),
    )
    await memory.initialize()
    return memory


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ingress", ["local_documents", "obsidian_vault", "manual_entry", "markdown_import"]
)
async def test_self_reports_reach_portrait_without_quoted_or_third_party_facts(tmp_path, ingress):
    adapter = _QualityAdapter(_payload())
    memory = await _memory(tmp_path, adapter)
    service = None
    try:
        for ref, name, kind in [
            ("group:diiv", "DIIV", "group"),
            ("food:coffee", "咖啡", "food"),
            ("person:alice", "Alice", "person"),
        ]:
            await memory.l2_entity_catalog.upsert_entity(
                entity_id=ref, canonical_name=name, entity_type=kind
            )
        if ingress == "markdown_import":
            path = tmp_path / "note.md"
            path.write_text(_NOTE)
            service = HistoryImportService(
                store=HistoryImportStore(db_path=memory.memory_db_path), memory=memory
            )
            preview = await service.preview_markdown_paths([str(path)])
            await service.confirm(
                job_id=preview.job_id,
                confirm_personal_writing=True,
                included_source_ids=preview.included_source_ids,
            )
            await _wait_for_import_and_l2(service, memory, job_id=preview.job_id)
        elif ingress == "manual_entry":
            entries = ManualEntryStore(db_path=memory.memory_db_path)
            entry = ManualEntry(
                entry_id="note", created_at=1_790_000_001.0, event_at=1_790_000_000.0, body=_NOTE
            )
            await entries.create(entry)
            await ManualEntryWorkflow(
                store=entries, projector=ManualEntryL1Projector(memory=memory), memory=memory
            ).project_and_link(entry=entry, predecessor_event_id=None)
            await memory.flush_l2_projection_jobs()
            await _wait(memory)
        else:
            receipt = await memory.ingest_event(_source_event(ingress, _NOTE))
            assert receipt["l2_job_enqueued"] is True
            await _wait(memory)
        assert _NOTE in adapter.calls[0]["prompt"]
        claims = await memory.l2.list_grounded_claims(user_id="local_user")
        assert len(claims) == 6
        assert {row["object_value"] for row in claims}.isdisjoint(
            {"苏眠", "爵士乐", "画画", "游泳"}
        )
        negative = next(row for row in claims if row["object_value"] == "food:coffee")
        assert negative["polarity"] == "negative"
        third_party = next(row for row in claims if row["object_value"] == "艾琳")
        assert third_party["subject_ref"] == "person:alice"
        name = next(row for row in claims if row["object_value"] == "明日香")
        evidence = (await memory.l2.get_grounded_claim(name["claim_id"]))["evidence"][0]
        locator = evidence["evidence_locator"]
        assert locator["attribution"] == "author_prose"
        assert locator["start"] == _NOTE.rindex(_NAME)
        assert _NOTE[locator["start"] : locator["end"]] == _NAME
        assertions = await memory.l2.list_current_assertions(
            entity_id="user:local_user", committed_only=False
        )
        assert sorted(row["trait_name"] for row in assertions) == sorted(
            [
                "identity.real_name",
                "communication.address.preferred",
                "preference.affinity",
            ]
        )
        assert {
            row["trait_value"] for row in assertions if row["trait_name"] == "preference.affinity"
        } == {"like"}
        reviews = await memory.l2.list_pending_reviews(subject_id="user:local_user")
        assert [row["kind"] for row in reviews] == ["goal_currentness"]
        portrait = await UserPortraitProjectionBuilder(memory.l2).build("local_user")
        assert len(portrait.prompt_summary) == 2
        assert "尚未形成长期结论" in " ".join(portrait.prompt_summary)
        for assertion in assertions:
            await memory.l2.apply_user_feedback(
                assertion_id=assertion["assertion_id"], feedback="confirmed"
            )
        portrait = await UserPortraitProjectionBuilder(memory.l2).build("local_user")
        rendered = json.dumps(
            {"world": portrait.world, "recent": portrait.recent, "prompt": portrait.prompt_summary},
            ensure_ascii=False,
        )
        for expected in ["明日香", "小明", "DIIV"]:
            assert expected in rendered
        for excluded in ["苏眠", "艾琳", "爵士乐", "画画", "游泳", "2099", "咖啡"]:
            assert excluded not in rendered
    finally:
        if service is not None:
            await service.stop()
        await memory.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["local_documents_search", "obsidian_vault_search"])
async def test_search_only_sources_never_enter_extraction_or_portrait(tmp_path, source):
    adapter = _QualityAdapter(_payload())
    memory = await _memory(tmp_path, adapter)
    try:
        receipt = await memory.ingest_event(_source_event(source, _NOTE, cognition=False))
        assert receipt["l2_job_enqueued"] is False
        assert adapter.calls == []
        assert await memory.l2.list_grounded_claims() == []
        assert not (
            await UserPortraitProjectionBuilder(memory.l2).build("local_user")
        ).prompt_summary
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_quote_only_edit_retires_prior_self_portrait(tmp_path):
    memory, adapter = await _open_store(tmp_path, "{}")
    try:
        entries = ManualEntryStore(db_path=memory.memory_db_path)
        projector = ManualEntryL1Projector(memory=memory)
        workflow = ManualEntryWorkflow(store=entries, projector=projector, memory=memory)
        entry = ManualEntry(
            entry_id="note",
            created_at=1_790_000_001.0,
            event_at=1_790_000_000.0,
            body=_NAME,
            body_doc=_doc(_NAME),
        )
        adapter._responses = [
            _response(
                event_id=projector.event_id_for(entry, predecessor_event_id=None),
                object_ref="明日香",
                evidence=_NAME,
                entities=[],
                predicate="REAL_NAME",
                object_type="person",
                fact_kind="explicit_fact",
            )
        ]
        await entries.create(entry)
        await workflow.project_and_link(entry=entry, predecessor_event_id=None)
        await memory.flush_l2_projection_jobs()
        await _wait(memory)
        assert (await UserPortraitProjectionBuilder(memory.l2).build("local_user")).prompt_summary
        original_id = entry.l1_event_id
        quoted = replace(entry, body_doc=_doc(_NAME, kind="blockquote"))
        adapter._responses = [
            _response(
                event_id=projector.event_id_for(quoted, predecessor_event_id=original_id),
                object_ref="明日香",
                evidence=_NAME,
                entities=[],
                predicate="REAL_NAME",
                object_type="person",
                fact_kind="explicit_fact",
            )
        ]
        await workflow.replace_and_project(
            entry=quoted, predecessor_event_id=original_id, reason="manual_entry_update"
        )
        await memory.flush_l2_projection_jobs()
        await _wait(memory, completed=2)
        assert quoted.l1_event_id != original_id
        assert (await memory.l1.get_event(original_id))["deleted_at"] is not None
        assert await memory.l2.list_current_assertions(entity_id="user:local_user") == []
        assert not (
            await UserPortraitProjectionBuilder(memory.l2).build("local_user")
        ).prompt_summary
    finally:
        await memory.shutdown()
