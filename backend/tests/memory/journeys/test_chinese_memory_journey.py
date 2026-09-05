"""Chinese memory journeys over real stores, public routes and prompt consumers.

The default provider is a scripted transport, including deliberately unsafe model
claims. It tests host governance, not model accuracy. The opt-in live variant uses
one explicitly configured OpenAI-compatible provider for extraction and answers.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from _shared.memory_schema import apply_memory_shared_schema
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.api.routers.memory.router import memory_router
from magi.bootstrap.tool_capabilities import _HostMemoryQueryPort
from magi.context.assembler import PromptContextAssembler, PromptContextRenderer
from magi.context.user_profile_service import UserProfileService
from magi.memory import MemoryStoreTuning, UnifiedMemoryStore
from magi.memory.history_imports.service import HistoryImportService
from magi.memory.history_imports.store import HistoryImportStore
from magi.memory.hybrid_retrieval.models import RetrievalConfig
from magi.memory.hybrid_retrieval.service import HybridRetrievalService
from magi.tools.builtin.memory_query_tool import MemoryQueryTool
from magi.tools.schema import ToolExecutionContext
from magi_plugin_sdk.capabilities import ToolCapabilities

CASES = json.loads((Path(__file__).parent / "fixtures/chinese_memory.json").read_text())["cases"]


class ScriptedTransport:
    provider_name = "openai"
    model_name = "scripted-memory-journey"

    def __init__(self):
        self.calls = 0
        self._client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=self.create))
        )

    async def create(self, **kwargs):
        self.calls += 1
        messages = kwargs.get("messages", [])
        system = str(messages[0].get("content", "")) if messages else ""
        prompt = str(messages[-1].get("content", "")) if messages else ""
        if "## Messages to Analyze" in prompt:
            window = prompt.split("## Messages to Analyze", 1)[1].split("## Focal Subject", 1)[0]
            entries = re.findall(
                r"### \[USER\] \[#([^\]]+)\][^\n]*\n(.*?)(?=\n### |\Z)", window, re.S
            )
            claims = []
            for event_id, content in entries:
                for case in CASES:
                    if case["text"] in content:
                        claims.append({**case["claim"], "supporting_event_ids": [event_id]})
            entities = [
                {
                    "surface": claim["object_ref"],
                    "normalized_name": claim["object_ref"],
                    "entity_type": claim["object_type"],
                    "specificity": "concrete",
                    "is_new": True,
                    "alias_signals": [],
                    "confidence": 0.99,
                }
                for claim in claims
                if claim["predicate"] == "LIKES"
            ]
            payload = {
                "entities": entities,
                "fact_claims": claims,
                "resolved_refs": [],
                "diagnostics": {"entity_status": "found" if entities else "not_found"},
            }
        elif "FORGOTTEN_JOURNEY" in system:
            assert "journey-stable_preference" not in prompt
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="现有记忆不足以确认。", tool_calls=[], role="assistant"
                        ),
                        finish_reason="stop",
                    )
                ],
                usage=None,
            )
        elif "ANSWER_JOURNEY" in system:
            # A transport assertion verifies the real prompt receives the corrected
            # name; no answer-quality score is derived from this scripted response.
            assert "明日香改名" in prompt
            payload = None
        else:
            payload = {"summaries": []}
        content = (
            "你现在叫明日香改名。" if payload is None else json.dumps(payload, ensure_ascii=False)
        )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content, tool_calls=[], role="assistant"),
                    finish_reason="stop",
                )
            ],
            usage=None,
        )


class ScenarioPool:
    def __init__(self, adapter):
        self.adapter = adapter

    def get(self, scenario):
        return self.adapter


def memory_at(path, adapter):
    return UnifiedMemoryStore(
        persist_dir=str(path / "memory"),
        l1_db_path=str(path / "l1.db"),
        memory_db_path=str(path / "memory.db"),
        archive_dir_path=str(path / "archive"),
        enable_l0=False,
        enable_l3=True,
        enable_l4=False,
        l2_batch_flush_interval_seconds=0,
        scenario_llm_pool=ScenarioPool(adapter),
        tuning=MemoryStoreTuning(
            enable_l1_vectors=False,
            enable_l2_vectors=False,
            enable_l3_vectors=False,
            enable_l4_vectors=False,
            enable_l3_llm_summary=False,
            async_embeddings=False,
        ),
    )


async def wait_for_projection(memory):
    for _ in range(1000):
        backlog = await memory.l2.get_projection_backlog_stats()
        if backlog.get("failed"):
            pytest.fail(f"Projection failed: {backlog}")
        if not backlog.get("pending") and not backlog.get("claimed"):
            await memory.l2_pipeline._reconcile_queue.join()
            await memory.l2_pipeline._snapshot_queue.join()
            return
        await asyncio.sleep(0.02)
    pytest.fail("Memory projection did not settle")


def event_for(case, timestamp):
    return {
        "id": "journey-" + case["id"],
        "type": "UserMessage",
        "timestamp": timestamp,
        "source": "chat",
        "level": 1,
        "data": {"user_id": "local_user", "session_id": "first-session", "content": case["text"]},
    }


async def recalled(memory, query):
    port = _HostMemoryQueryPort()
    port._service = HybridRetrievalService(
        memory,
        config=RetrievalConfig(
            intent_decider_llm_enabled=False,
            intent_shadow_eval_enabled=False,
            grounding_filter_enabled=False,
            query_expansion_enabled=False,
        ),
    )
    tool = MemoryQueryTool()
    result = await tool.execute(
        {"query": query, "query_mode": "episode_recall", "session_id": "second-session"},
        ToolExecutionContext(
            agent_id="journey",
            capabilities=ToolCapabilities(memory_query=port),
            env_vars={"user_id": "local_user"},
        ),
    )
    assert result.success, result.error
    return result.data["historical_recall"]


async def prompt_for(memory):
    assembler = PromptContextAssembler(user_profile_service=UserProfileService(memory, cache_ttl=0))
    assembled = await assembler.assemble(
        agent_id="journey",
        agent_type="chat",
        scenario="chat",
        task_category="chat",
        user_id="local_user",
        persona_name="default",
        user_message="我现在叫什么？",
    )
    return PromptContextRenderer().render_prompt_layers(assembled).working_context


async def run_journey(tmp_path, monkeypatch, adapter):
    from magi.api.routers.memory.l2 import knowledge_routes, correction_routes
    from magi.api.routers.memory import quality_routes, portrait_self_routes, stories_routes
    from magi.memory.l3.models import L3Candidate
    from magi.llm import LLMProviderBridge

    await apply_memory_shared_schema(str(tmp_path / "memory.db"))
    memory = memory_at(tmp_path, adapter)
    await memory.initialize()
    import_service = None
    events = [event_for(case, time.time() - 3600 + i) for i, case in enumerate(CASES)]
    try:
        for event in events:
            await memory.ingest_event(event)
        await wait_for_projection(memory)
        claims = await memory.l2.list_grounded_claims(user_id="local_user")
        assertions = await memory.l2.list_current_assertions(
            entity_id="user:local_user", committed_only=False
        )
        values = {str(row.get("natural_summary") or row["trait_value"]) for row in assertions}
        assert any("明日香2" in value for value in values)
        assert not any("明日香3" in value for value in values)
        assert not any("红烧肉" in value or "重金属" in value for value in values)
        assert any("爵士乐" in value for value in values), assertions
        diiv = next(row for row in assertions if "DIIV" in str(row.get("natural_summary")))
        assert diiv["temporal_scope"] == "stable"
        recent = next(row for row in assertions if "环境音乐" in str(row.get("natural_summary")))
        assert recent["temporal_scope"] == "recent"
        assert recent["expires_at"] is not None
        stats = memory.get_l2_pipeline_stats()
        assert stats["events_model_admitted"] > 0
        assert stats["claims_grounded"] >= len(claims)
        assert stats["extract_failed"] == 0
        assert stats["claims_rejected"] >= 0

        # The public correction route updates the same persisted projection used
        # by the real prompt consumer. No test seeds profile/assertion rows.
        app = FastAPI()
        app.include_router(
            _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]),
            prefix="/api/memory",
        )
        for module in (knowledge_routes, correction_routes, quality_routes):
            monkeypatch.setattr(module, "_resolve_unified_memory", lambda: memory)
        monkeypatch.setattr(portrait_self_routes, "get_unified_memory", lambda: memory)
        monkeypatch.setattr(stories_routes, "_get_memory", lambda: memory)
        summary_candidate = L3Candidate(
            content="你长期关注爵士乐。",
            source_event_ids=["journey-stable_preference"],
            summary_category="state_change",
            summary_type="insight",
            review_state="pending_confirmation",
            insight_key="journey:music",
        )
        summary = await memory.l3.upsert_candidate(candidate=summary_candidate)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            name = next(row for row in assertions if row["trait_name"] == "identity.real_name")
            response = await client.post(
                "/api/memory/l2/corrections",
                json={
                    "request_id": "journey-correction",
                    "target": {"kind": "assertion", "id": name["assertion_id"]},
                    "correction_kind": "record_error",
                    "replacement": {"value": "明日香改名"},
                    "expected_updated_at": name["updated_at"],
                },
            )
            assert response.status_code == 200, response.text
            portrait = await client.get(
                "/api/memory/portrait/self", params={"user_id": "local_user"}
            )
            assert portrait.status_code == 200
            assert portrait.json()["is_stale"] is False
            rejected = await client.patch(
                f"/api/memory/stories/{summary['summary_id']}/review",
                json={"review_state": "rejected"},
            )
            assert rejected.status_code == 200
            assert await memory.l3.get_summary_by_id(summary["summary_id"]) is None
            replay = await memory.l3.upsert_candidate(candidate=summary_candidate)
            assert replay["review_state"] == "rejected"
            quality = (
                await client.get("/api/memory/quality", params={"user_id": "local_user"})
            ).json()
            assert quality["stored"]["l1_events"] >= len(events)
        prompt = await prompt_for(memory)
        assert "明日香改名" in prompt
        assert "明日香2" not in prompt
        response = await LLMProviderBridge(adapter).chat_response(
            system_prompt="ANSWER_JOURNEY: Answer the user in Chinese using only the provided current profile.",
            messages=[{"role": "user", "content": prompt + "\n我现在叫什么？"}],
            temperature=0,
            disable_thinking=True,
        )
        assert "明日香改名" in response.content
        assert "明日香2" not in response.content
        recall = await recalled(memory, "我说过喜欢爵士乐吗")
        assert "爵士乐" in json.dumps(recall, ensure_ascii=False)

        # Import the same authored source through the production importer.
        document = tmp_path / "近况.md"
        document.write_text("# 近况\n\n" + CASES[4]["text"], encoding="utf-8")
        import_service = HistoryImportService(
            store=HistoryImportStore(db_path=str(tmp_path / "memory.db")), memory=memory
        )
        preview = await import_service.preview_markdown_paths([str(document)])
        await import_service.confirm(
            job_id=preview.job_id,
            confirm_personal_writing=True,
            included_source_ids=preview.included_source_ids,
        )
        for _ in range(500):
            if (await import_service.get_job(preview.job_id)).status == "completed":
                break
            await asyncio.sleep(0.02)
        else:
            pytest.fail("History import did not complete")
        await wait_for_projection(memory)
        imported = await memory.l1.query_events(source_filters=["history_import"])
        assert len(imported) == 1
        import_id = imported[0]["event_id"]
        imported_claims = await memory.l2.list_grounded_claims(user_id="local_user")
        assert len(imported_claims) >= len(claims)

        # Forget the original music source and the imported document, then try
        # delivery again after a full store restart.
        forgotten = ["journey-stable_preference", "journey-mixed_horizon", import_id]
        assert await memory.forget_source_events(forgotten, reason="journey_user_request") == 3
        assert "爵士乐" not in await prompt_for(memory)
        await import_service.stop()
        import_service = None
        await memory.shutdown()
        memory = memory_at(tmp_path, adapter)
        await memory.initialize()
        for event in events:
            replay_result = await memory.ingest_event(event)
            if event["id"] in forgotten:
                assert replay_result["skip_reason"] == "source_event_forgotten"
        await wait_for_projection(memory)
        assert await memory.l1.get_user_visible_event("journey-stable_preference") is None
        assert await memory.l1.get_user_visible_event(import_id) is None
        assert await memory.l3.get_summary_by_id(summary["summary_id"]) is None
        assert "爵士乐" not in await prompt_for(memory)
        assert "明日香改名" in await prompt_for(memory)
        recall = await recalled(memory, "我说过喜欢爵士乐吗")
        assert "爵士乐" not in json.dumps(recall["findings"], ensure_ascii=False)
        assert not any(event_id in json.dumps(recall["findings"]) for event_id in forgotten)
        answer = await LLMProviderBridge(adapter).chat_response(
            system_prompt="FORGOTTEN_JOURNEY: Answer only from the provided findings. A found status means candidates exist, not that they answer this question. State uncertainty if the evidence does not establish the requested preference.",
            messages=[
                {
                    "role": "user",
                    "content": json.dumps(recall, ensure_ascii=False) + "\n我还喜欢爵士乐吗？",
                }
            ],
            temperature=0,
            disable_thinking=True,
        )
        assert re.search("不足|不确定|无法|没有|不能确认|未找到|不清楚", answer.content)
        assert "你喜欢爵士乐" not in answer.content
        return {
            "mode": "live" if not isinstance(adapter, ScriptedTransport) else "scripted_transport",
            "case_count": len(CASES),
            "source_paths": ["chat", "history_import"],
            "restart_replay": "passed",
            "correction": "passed",
            "forgotten_recall": "passed",
            "cross_session_prompt_and_answer": "passed",
        }
    finally:
        if import_service is not None:
            await import_service.stop()
        await memory.shutdown()


@pytest.mark.asyncio
async def test_chinese_memory_journey(tmp_path, monkeypatch):
    result = await run_journey(tmp_path, monkeypatch, ScriptedTransport())
    assert result["mode"] == "scripted_transport"


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("MAGI_LIVE_MEMORY_EVAL") != "1",
    reason="Explicit live provider configuration required",
)
async def test_live_chinese_memory_journey(tmp_path, monkeypatch):
    from magi.llm.openai import OpenAIAdapter

    key, model = os.environ.get("MAGI_EVAL_API_KEY"), os.environ.get("MAGI_EVAL_MODEL")
    assert key and model, "MAGI_EVAL_API_KEY and MAGI_EVAL_MODEL are required"
    adapter = OpenAIAdapter(
        api_key=key, model=model, base_url=os.environ.get("MAGI_EVAL_BASE_URL"), timeout=30
    )
    try:
        await run_journey(tmp_path, monkeypatch, adapter)
    finally:
        await adapter._client.close()
