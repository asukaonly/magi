"""Verification tests for P1-D2: two-layer privacy filter, cloud LLM egress guard, and Context Sent trace."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from _shared.memory_stores import build_memory_store
from magi.agent.execution.function_calling.llm import _apply_cloud_egress_guard_and_record_context
from magi.agent.execution.function_calling.llm_invocation import FunctionCallingLlmRequest
from magi.api.routers.messages_content import message_content_router
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.awareness.ingestion_gateway import SourceIngestionGateway
from magi.awareness.source_base import Source
from magi.awareness.source_output import (
    ActivityFacet,
    SourceActivity,
    SourceNarration,
    SourceOutput,
)
from magi.config.memory_models import PrivacyFilterSettings
from magi.config.models import ThinkingDepth
from magi.context.recent_life_brief import RecentLifeBriefService
from magi.memory.event_contracts import IngestTarget, MemoryDomain, MemoryEvent, RetentionClass, TomDepth
from magi.memory.hybrid_retrieval.models import RetrievalQuery
from magi.memory.hybrid_retrieval.service import HybridRetrievalService
from magi.memory.privacy_filter import (
    evaluate_source_privacy,
    is_local_llm_provider,
    redact_cloud_egress_text,
)
from magi.memory.source_ingestion import SourceEventCommitter
from magi.runtime_trace.context_sent import get_context_sent_store


class _FakeSource(Source):
    def __init__(self, source_id: str) -> None:
        super().__init__()
        self.source_id = source_id
        self.display_name = source_id

    async def build_output(self, item):
        return item


class _StubCloudLLM:
    provider_name = "anthropic"
    model_name = "claude-sonnet-4-6"
    base_url = "https://api.anthropic.com"


class _StubLocalLLM:
    provider_name = "ollama"
    model_name = "qwen2.5:14b"
    base_url = "http://127.0.0.1:11434/v1"


def test_privacy_filter_detects_domains_paths_secrets_and_provider_locality():
    assert is_local_llm_provider(provider="ollama", base_url="http://127.0.0.1:11434") is True
    assert is_local_llm_provider(provider="openai", base_url="https://api.openai.com/v1") is False

    bank_decision = evaluate_source_privacy(
        source_name="chrome_history",
        content="Visited Online Banking Sign In",
        metadata={"url": "https://secure.chase.com/web/auth/login"},
    )
    assert bank_decision.action == "local_only"
    assert bank_decision.reason == "blocked_domain_pattern"

    ssh_decision = evaluate_source_privacy(
        source_name="terminal_history",
        content="cat ~/.ssh/id_rsa",
        metadata={"cwd": "/Users/asuka"},
    )
    assert ssh_decision.action == "local_only"
    assert ssh_decision.reason == "blocked_path_pattern"

    secret_decision = evaluate_source_privacy(
        source_name="terminal_history",
        content="export OPENAI_API_KEY=sk-live-secret1234567890",
        metadata={},
    )
    assert secret_decision.action == "local_only"
    assert secret_decision.reason == "sensitive_secret_detected"

    benign_decision = evaluate_source_privacy(
        source_name="chrome_history",
        content="Read Rust async book",
        metadata={"url": "https://doc.rust-lang.org/book/"},
    )
    assert benign_decision.action == "allow"

    drop_decision = evaluate_source_privacy(
        source_name="chrome_history",
        content="Visited Chase",
        metadata={"url": "https://secure.chase.com/login"},
        settings=PrivacyFilterSettings(default_action="drop"),
    )
    assert drop_decision.action == "drop"

    redacted_text, changed = redact_cloud_egress_text(
        "key=sk-live-secret1234567890 card=4532-0151-1283-0366 aws=AKIAIOSFODNN7EXAMPLE"
    )
    assert changed is True
    assert "sk-live-secret1234567890" not in redacted_text
    assert "4532-0151-1283-0366" not in redacted_text
    assert "AKIAIOSFODNN7EXAMPLE" not in redacted_text


@pytest.mark.asyncio
async def test_ingestion_gateway_tags_local_only_and_drops_when_configured(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "memory"
    store = build_memory_store(
        l1_db_path=str(data_dir / "l1_events.db"),
        memory_db_path=str(data_dir / "memory.db"),
        enable_l0=False,
        enable_l1=True,
        enable_l2=False,
        enable_l3=False,
        enable_l4=False,
    )
    await store.initialize()
    try:
        event_bus = SimpleNamespace(publish=AsyncMock(return_value=True))
        gateway = SourceIngestionGateway(
            event_bus=event_bus,
            memory_committer=SourceEventCommitter(unified_memory=store),
        )
        chrome_source = _FakeSource("chrome_history")
        now = time.time()

        # 1. Default mode ("local_only"): banking URL stored with exclude_from_llm=True
        bank_output = SourceOutput(
            source_type="chrome_history",
            source_item_id="chrome-bank-1",
            occurred_at=now - 60,
            captured_at=now,
            activity=SourceActivity(
                source=ActivityFacet(code="chrome", i18n_key="source.chrome", fallback="Chrome"),
                action=ActivityFacet(code="visited", i18n_key="action.visited", fallback="visited"),
            ),
            narration=SourceNarration(
                title="Chase Online Login",
                body="Visited Chase Online Login",
            ),
            domain_payload={
                "url": "https://secure.chase.com/login",
                "title": "Chase Online Login",
                "summary": "Visited Chase Online Login",
            },
        )
        bank_res = await gateway.ingest(chrome_source, bank_output)
        assert bank_res.ingested is True
        rows = await store.l1.query_events(source_filters=["chrome_history"], limit=10)
        assert len(rows) == 1
        assert rows[0]["metadata_json"]["exclude_from_llm"] is True

        # 2. Drop mode: sensitive URL is skipped before L1 commit
        monkeypatch.setattr(
            "magi.memory.privacy_filter.resolve_privacy_filter_settings",
            lambda settings=None: settings or PrivacyFilterSettings(default_action="drop"),
        )
        drop_output = SourceOutput(
            source_type="chrome_history",
            source_item_id="chrome-bank-2",
            occurred_at=now - 30,
            captured_at=now,
            activity=SourceActivity(
                source=ActivityFacet(code="chrome", i18n_key="source.chrome", fallback="Chrome"),
                action=ActivityFacet(code="visited", i18n_key="action.visited", fallback="visited"),
            ),
            narration=SourceNarration(
                title="1Password Vault",
                body="Opened 1Password Vault",
            ),
            domain_payload={
                "url": "https://my.1password.com/vaults",
                "title": "1Password Vault",
                "summary": "Opened 1Password Vault",
            },
        )
        drop_res = await gateway.ingest(chrome_source, drop_output)
        assert drop_res.ingested is False
        assert drop_res.stats["memory_outcome"] == "privacy_dropped"
        rows_after = await store.l1.query_events(source_filters=["chrome_history"], limit=10)
        assert len(rows_after) == 1
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_cloud_llm_egress_zero_leakage_while_local_llm_sees_local_only(tmp_path: Path):
    data_dir = tmp_path / "memory"
    store = build_memory_store(
        l1_db_path=str(data_dir / "l1_events.db"),
        memory_db_path=str(data_dir / "memory.db"),
        enable_l0=False,
        enable_l1=True,
        enable_l2=False,
        enable_l3=False,
        enable_l4=False,
    )
    await store.initialize()
    try:
        now = time.time()
        events = [
            MemoryEvent(
                event_id="evt-bank",
                correlation_id="evt-bank",
                timestamp=now - 120,
                created_at=now - 120,
                event_type="SOURCE_EVENT",
                source="chrome_history",
                source_item_id="chrome-bank",
                memory_domain=MemoryDomain.EXTERNAL_ACTIVITY,
                ingest_target=IngestTarget.L1_ONLY,
                cognition_eligible=False,
                tom_depth=TomDepth.NONE,
                retention_class=RetentionClass.COMPRESSIBLE,
                session_id=None,
                turn_id=None,
                user_id="local_user",
                task_id=None,
                content="Visited Chase banking portal https://secure.chase.com/login",
                author_type="external",
                content_type="observation",
                importance_score=0.5,
                level=1,
                metadata_json={"url": "https://secure.chase.com/login", "exclude_from_llm": True},
            ),
            MemoryEvent(
                event_id="evt-terminal-secret",
                correlation_id="evt-terminal-secret",
                timestamp=now - 90,
                created_at=now - 90,
                event_type="SOURCE_EVENT",
                source="terminal_history",
                source_item_id="term-secret",
                memory_domain=MemoryDomain.EXTERNAL_ACTIVITY,
                ingest_target=IngestTarget.L1_ONLY,
                cognition_eligible=False,
                tom_depth=TomDepth.NONE,
                retention_class=RetentionClass.COMPRESSIBLE,
                session_id=None,
                turn_id=None,
                user_id="local_user",
                task_id=None,
                content="curl -H 'Authorization: Bearer sk-live-secret1234567890' https://api.example.com",
                author_type="external",
                content_type="observation",
                importance_score=0.5,
                level=1,
                metadata_json={"command": "curl -H 'Authorization: Bearer sk-live-secret1234567890'"},
            ),
            MemoryEvent(
                event_id="evt-manual-private",
                correlation_id="evt-manual-private",
                timestamp=now - 60,
                created_at=now - 60,
                event_type="manual_entry",
                source="manual_entry",
                source_item_id="manual-priv-1",
                memory_domain=MemoryDomain.USER_AUTHORED,
                ingest_target=IngestTarget.L1_ONLY,
                cognition_eligible=False,
                tom_depth=TomDepth.NONE,
                retention_class=RetentionClass.PERMANENT,
                session_id=None,
                turn_id=None,
                user_id="local_user",
                task_id=None,
                content="Private personal medical note only for local model",
                author_type="user",
                content_type="text",
                importance_score=0.8,
                level=1,
                metadata_json={"exclude_from_llm": True},
            ),
            MemoryEvent(
                event_id="evt-safe-docs",
                correlation_id="evt-safe-docs",
                timestamp=now - 30,
                created_at=now - 30,
                event_type="SOURCE_EVENT",
                source="chrome_history",
                source_item_id="chrome-docs-1",
                memory_domain=MemoryDomain.EXTERNAL_ACTIVITY,
                ingest_target=IngestTarget.L1_ONLY,
                cognition_eligible=False,
                tom_depth=TomDepth.NONE,
                retention_class=RetentionClass.COMPRESSIBLE,
                session_id=None,
                turn_id=None,
                user_id="local_user",
                task_id=None,
                content="Read Rust async patterns on doc.rust-lang.org",
                author_type="external",
                content_type="observation",
                importance_score=0.5,
                level=1,
                metadata_json={"url": "https://doc.rust-lang.org/book/", "title": "Rust Async Book"},
            ),
        ]
        for ev in events:
            await store.l1.store(ev)

        # 1. RecentLifeBrief for cloud vs local
        brief_service = RecentLifeBriefService(store)
        cloud_brief = await brief_service.build_brief(
            user_id="local_user",
            now=now,
            is_local_provider=False,
        )
        cloud_text = "\n".join(cloud_brief.entries)
        assert "chase.com" not in cloud_text.lower()
        assert "sk-live-secret1234567890" not in cloud_text
        assert "Private personal medical note" not in cloud_text
        assert "Rust Async Book" in cloud_text
        assert cloud_brief.excluded_local_only_count == 3

        local_brief = await brief_service.build_brief(
            user_id="local_user",
            now=now,
            is_local_provider=True,
        )
        local_text = "\n".join(local_brief.entries)
        assert "Private personal medical note" in local_text
        assert local_brief.excluded_local_only_count == 0

        # 2. HybridRetrievalService (memory_query backend) for cloud vs local
        retrieval = HybridRetrievalService(store)
        cloud_payload = await retrieval.query(
            RetrievalQuery(
                query="medical note chase secret Rust",
                user_id="local_user",
                query_mode="event_stream",
                limit=10,
                is_local_llm=False,
            )
        )
        cloud_ids = {row["event_id"] for row in cloud_payload.l1_events}
        assert "evt-bank" not in cloud_ids
        assert "evt-terminal-secret" not in cloud_ids
        assert "evt-manual-private" not in cloud_ids
        assert "evt-safe-docs" in cloud_ids
        assert "sk-live-secret1234567890" not in str(cloud_payload)

        local_payload = await retrieval.query(
            RetrievalQuery(
                query="medical note",
                user_id="local_user",
                query_mode="event_stream",
                limit=10,
                is_local_llm=True,
            )
        )
        local_ids = {row["event_id"] for row in local_payload.l1_events}
        assert "evt-manual-private" in local_ids
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_cloud_egress_guard_records_sanitized_context_sent_and_exposes_via_trace_route(
    monkeypatch,
):
    store = get_context_sent_store()
    store.clear()

    request = FunctionCallingLlmRequest(
        request_id="req-1",
        request_kind="function_calling:chat_tools",
        system_prompt=(
            "# System Definition\nBe helpful.\n\n"
            "# Recent Authorized Activity (Background Only)\n"
            "- Browsing: Rust Async Book [chrome_history | evt-safe-docs]\n"
        ),
        messages=[
            {
                "role": "user",
                "content": (
                    "# Memory Library\n"
                    "- User prefers concise TypeScript answers\n\n"
                    "Here is my leaked token sk-live-secret1234567890"
                ),
            }
        ],
        thinking_depth=ThinkingDepth.NONE,
        timeout_seconds=None,
        session_id="sess-privacy-1",
        turn_id="turn-privacy-1",
        execution_agent_id="chat_agent",
        execution_preset="chat",
        iteration=1,
    )

    sanitized = _apply_cloud_egress_guard_and_record_context(_StubCloudLLM(), request)
    assert "sk-live-secret1234567890" not in sanitized.messages[0]["content"]

    recorded = store.get(session_id="sess-privacy-1", turn_id="turn-privacy-1")
    assert recorded is not None
    assert recorded["provider"] == "anthropic"
    assert recorded["model"] == "claude-sonnet-4-6"
    assert recorded["is_local_provider"] is False
    assert recorded["redacted"] is True
    assert "sk-live-secret1234567890" not in str(recorded)
    assert any("Rust Async Book" in item for item in recorded["recent_life_brief_items"])
    assert any("concise TypeScript" in item for item in recorded["recalled_memory_items"])

    # Verify GET /api/messages/trace includes context_sent through the real public router allowlist
    class _FakeTraceReadService:
        async def aget_trace_snapshot(self, *, user_id: str, session_id: str, turn_id: str):
            return {
                "turn_id": turn_id,
                "user_id": user_id,
                "session_id": session_id,
                "status": "completed",
                "mode": "function_calling",
                "summary": {
                    "turn_id": turn_id,
                    "mode": "function_calling",
                    "status": "completed",
                    "headline": "Done",
                    "active_steps": 0,
                    "completed_steps": 1,
                    "failed_steps": 0,
                    "duration_seconds": 0.4,
                    "trace_available": True,
                },
                "root": {
                    "id": "root-1",
                    "kind": "root",
                    "label": "Turn",
                    "status": "completed",
                    "metadata": {},
                    "children": [],
                },
                "context_sent": store.get(session_id=session_id, turn_id=turn_id),
            }

    monkeypatch.setattr(
        "magi.api.routers.messages_content.require_chat_read_service",
        lambda: object(),
    )
    monkeypatch.setattr(
        "magi.api.routers.messages_content.get_chat_trace_read_service",
        lambda: _FakeTraceReadService(),
    )
    app = FastAPI()
    app.include_router(
        _build_public_router(message_content_router, _PUBLIC_ROUTE_METHODS["messages"]),
        prefix="/api/messages",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.get(
            "/api/messages/trace",
            params={"session_id": "sess-privacy-1", "turn_id": "turn-privacy-1"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    ctx = body["trace"]["context_sent"]
    assert ctx["provider"] == "anthropic"
    assert ctx["model"] == "claude-sonnet-4-6"
    assert ctx["redacted"] is True
    assert "sk-live-secret1234567890" not in str(ctx)

    # Local LLM records is_local_provider=True and skips cloud redaction
    local_req = FunctionCallingLlmRequest(
        request_id="req-2",
        request_kind="function_calling:chat_tools",
        system_prompt="# System Definition\nLocal mode.",
        messages=[{"role": "user", "content": "Local private note"}],
        thinking_depth=ThinkingDepth.NONE,
        timeout_seconds=None,
        session_id="sess-privacy-1",
        turn_id="turn-privacy-local",
        execution_agent_id="chat_agent",
        execution_preset="chat",
        iteration=1,
    )
    _apply_cloud_egress_guard_and_record_context(_StubLocalLLM(), local_req)
    local_ctx = store.get(session_id="sess-privacy-1", turn_id="turn-privacy-local")
    assert local_ctx is not None
    assert local_ctx["is_local_provider"] is True
    assert local_ctx["redacted"] is False
