"""Tests for P1-B2: Ambient Recent Life Brief, empty-section omission, cues, and semantic reflection matching."""

from __future__ import annotations

from contextlib import asynccontextmanager
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from _shared.memory_stores import build_memory_store
from magi.config.models import PersonalitySettings
from magi.context.assembler import PromptContextAssembler
from magi.context.recent_life_brief import (
    RECENT_LIFE_BRIEF_MAX_TOKENS,
    RecentLifeBriefService,
    estimate_brief_tokens,
)
from magi.context.renderer import PromptContextRenderer
from magi.context.service import ContextAssemblyService
from magi.memory.embedding.embedding_service import EmbeddingResult
from magi.memory.event_contracts import (
    IngestTarget,
    MemoryDomain,
    MemoryEvent,
    RetentionClass,
    TomDepth,
)
from magi.memory.l3.models import L3Candidate
from magi.personality.persona_journal_service import PersonaJournalService
from magi.personality.reflection_store import ReflectionStore


def _make_external_event(
    *,
    event_id: str,
    user_id: str,
    source: str,
    event_type: str,
    content: str,
    timestamp: float,
    metadata: dict | None = None,
) -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        correlation_id=f"corr-{event_id}",
        timestamp=timestamp,
        created_at=timestamp,
        event_type=event_type,
        source=source,
        source_item_id=f"item-{event_id}",
        memory_domain=MemoryDomain.EXTERNAL_ACTIVITY,
        ingest_target=IngestTarget.L1_ONLY,
        cognition_eligible=True,
        tom_depth=TomDepth.NONE,
        retention_class=RetentionClass.COMPRESSIBLE,
        session_id=None,
        turn_id=None,
        user_id=user_id,
        task_id=None,
        content=content,
        author_type="user",
        content_type="text",
        importance_score=0.6,
        level=1,
        metadata_json=metadata,
    )


def _extract_recent_activity_section(working_context: str) -> str:
    marker = "# Recent Authorized Activity (Background Only)"
    assert marker in working_context
    tail = working_context[working_context.index(marker) :]
    lines = tail.splitlines()
    section_lines: list[str] = []
    for index, line in enumerate(lines):
        if index > 0 and line.startswith("# "):
            break
        section_lines.append(line)
    return "\n".join(section_lines).strip()


def _build_context_service(unified_memory) -> ContextAssemblyService:
    assembler = PromptContextAssembler(
        recent_life_brief_service=RecentLifeBriefService(unified_memory),
    )
    renderer = PromptContextRenderer()
    return ContextAssemblyService(
        agent_id="chat-test",
        agent_type="chat",
        prompt_context_assembler=assembler,
        prompt_context_renderer=renderer,
        retrieval_memory_provider=AsyncMock(return_value={}),
        retrieval_memory_availability_provider=lambda: True,
    )


@pytest.mark.asyncio
async def test_recent_life_brief_prompt_injection_token_cap_forget_and_latency(tmp_path) -> None:
    store = build_memory_store(
        persist_dir=str(tmp_path / "memory"),
        enable_l0=False,
        enable_l1=True,
        enable_l2=True,
        enable_l3=True,
        enable_l4=False,
    )
    await store.initialize()
    try:
        now = time.time()
        user_id = "user-b2"

        # 1. Cold-start empty user should get zero recent activity section and zero empty placeholders.
        service = _build_context_service(store)
        empty_pkg = await service.build_prompt_package(
            user_id=user_id,
            user_message="今天好累啊",
            task_category="chat",
        )
        assert "# Recent Authorized Activity" not in empty_pkg.working_context
        assert "# Memory Library" not in empty_pkg.working_context
        assert "* (empty)" not in empty_pkg.working_context
        assert "* (no preferences recorded)" not in empty_pkg.working_context

        # 2. Populate recent 72h Chrome, NetEase Music, Git, manual note, excluded note, and L3 day summary.
        events = [
            _make_external_event(
                event_id="ev-music-1",
                user_id=user_id,
                source="netease_music",
                event_type="MUSIC_PLAYED",
                content="Listened to Nujabes - Luv(sic) Part 3",
                timestamp=now - 3600 * 6,
                metadata={"track_title": "Luv(sic) Part 3", "artist": "Nujabes"},
            ),
            _make_external_event(
                event_id="ev-chrome-1",
                user_id=user_id,
                source="chrome_history",
                event_type="WEB_VISIT",
                content="Visited SQLite WAL documentation",
                timestamp=now - 3600 * 10,
                metadata={"title": "SQLite WAL Mode", "domain": "sqlite.org"},
            ),
            _make_external_event(
                event_id="ev-git-1",
                user_id=user_id,
                source="git_activity",
                event_type="GIT_COMMIT",
                content="Committed retrieval ranking fixes in magi",
                timestamp=now - 3600 * 12,
                metadata={"repo": "magi", "commit_message": "fix timeline hybrid search"},
            ),
            _make_external_event(
                event_id="ev-note-1",
                user_id=user_id,
                source="manual",
                event_type="manual_entry",
                content="今天项目收尾好累，压力大有点失眠",
                timestamp=now - 3600 * 3,
                metadata={"mood": "tired"},
            ),
            _make_external_event(
                event_id="ev-private-1",
                user_id=user_id,
                source="manual",
                event_type="manual_entry",
                content="SECRET_SHOULD_NOT_APPEAR",
                timestamp=now - 3600 * 2,
                metadata={"exclude_from_llm": True},
            ),
        ]
        for event in events:
            await store.l1.store(event)

        await store.l3.upsert_candidate(
            candidate=L3Candidate(
                summary_type="temporal",
                summary_category="day",
                content="Wrapped up timeline search debugging and unwound with Nujabes at night.",
                source_event_ids=["ev-git-1", "ev-music-1"],
                insight_key="day-brief-test",
            ),
            summary_overrides={"period_start": now - 3600 * 14, "period_end": now - 3600 * 2},
        )

        # 3. Cold miss assembly must succeed fast (<50ms is expected in normal env) with 0 LLM calls.
        t0 = time.perf_counter()
        pkg = await service.build_prompt_package(
            user_id=user_id,
            user_message="今天好累啊",
            task_category="chat",
        )
        cold_ms = (time.perf_counter() - t0) * 1000.0
        assert cold_ms < 500.0  # generous CI ceiling; hot cache is strictly checked below

        section = _extract_recent_activity_section(pkg.working_context)
        assert estimate_brief_tokens(section) <= RECENT_LIFE_BRIEF_MAX_TOKENS
        assert "[netease_music | ev-music-1]" in section
        assert "[chrome_history | ev-chrome-1]" in section
        assert "[git_activity | ev-git-1]" in section
        assert "[manual | ev-note-1]" in section
        assert "[l3 |" in section
        assert "SECRET_SHOULD_NOT_APPEAR" not in pkg.working_context
        assert "* (empty)" not in pkg.working_context
        assert "# Memory Library" not in pkg.working_context
        # Restrained 24h cue from low-mood manual note is attached to turn steer.
        assert "## Recent User Context Cue" in pkg.working_context
        assert "without lecturing" in pkg.working_context

        # 4. Hot cache hit must be fast (<5ms for brief lookup itself).
        brief_service = service._prompt_context_assembler.recent_life_brief_service
        assert brief_service is not None
        t_hit = time.perf_counter()
        cached_brief = await brief_service.build_brief(user_id=user_id)
        hit_ms = (time.perf_counter() - t_hit) * 1000.0
        assert hit_ms < 5.0
        assert cached_brief.entries

        # 5. Forgetting one event must invalidate cache immediately and drop it from prompt.
        forgotten = await store.forget_source_event("ev-chrome-1")
        assert forgotten is True

        pkg_after_forget = await service.build_prompt_package(
            user_id=user_id,
            user_message="今天好累啊",
            task_category="chat",
        )
        section_after = _extract_recent_activity_section(pkg_after_forget.working_context)
        assert "ev-chrome-1" not in section_after
        assert "SQLite WAL Mode" not in section_after
        assert "[netease_music | ev-music-1]" in section_after
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_recent_life_brief_strictly_enforces_350_token_cap_under_heavy_load(tmp_path) -> None:
    store = build_memory_store(
        persist_dir=str(tmp_path / "memory"),
        enable_l0=False,
        enable_l1=True,
        enable_l2=False,
        enable_l3=False,
        enable_l4=False,
    )
    await store.initialize()
    try:
        now = time.time()
        sources = [
            "manual",
            "netease_music",
            "git_activity",
            "calendar",
            "chrome_history",
            "photo_library",
            "screen_time",
            "terminal_history",
        ]
        for idx, source in enumerate(sources):
            for j in range(3):
                await store.l1.store(
                    _make_external_event(
                        event_id=f"ev-{source}-{j}",
                        user_id="user-heavy",
                        source=source,
                        event_type="ACTIVITY",
                        content=(
                            f"这是一条很长的活动记录描述用于验证近况摘要严格不超过三百五十个token预算 "
                            f"source={source} item={j} detail={'详细内容' * 15}"
                        ),
                        timestamp=now - (idx * 600 + j * 60),
                    )
                )

        brief_service = RecentLifeBriefService(store)
        brief = await brief_service.build_brief(user_id="user-heavy", now=now)
        rendered = "\n".join(PromptContextRenderer()._render_recent_life_brief(list(brief.entries)))
        assert brief.entries
        assert estimate_brief_tokens(rendered) <= RECENT_LIFE_BRIEF_MAX_TOKENS
        assert brief.estimated_tokens <= RECENT_LIFE_BRIEF_MAX_TOKENS
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_persona_journal_relevant_supports_semantic_and_chinese_lexical_matching(
    tmp_path,
    ensure_db_schema,
    monkeypatch,
) -> None:
    @asynccontextmanager
    async def guard():
        yield

    path = tmp_path / "growth.db"
    ensure_db_schema("growth_memory", path)
    settings = PersonalitySettings(enable_background_reflection=True)
    monkeypatch.setattr(
        "magi.personality.persona_journal_service.get_config",
        lambda: SimpleNamespace(agent=SimpleNamespace(personality=settings)),
    )
    persona = SimpleNamespace(
        persona_id="p1",
        updated_at=1,
        name="Magi",
        config=SimpleNamespace(
            description="Thoughtful",
            identity_core=SimpleNamespace(identity_statement="Stay grounded"),
            idiolect=None,
        ),
    )
    events = [
        {
            "event_id": "e1",
            "user_id": "u1",
            "source": "chat",
            "author_type": "user",
            "content": "最近总喜欢深夜循环听爵士乐放松。",
            "timestamp": time.time() - 1800,
        },
        {
            "event_id": "e2",
            "user_id": "u1",
            "source": "chat",
            "author_type": "user",
            "content": "我想把数据库迁移放到周末处理。",
            "timestamp": time.time() - 1700,
        },
    ]

    class _FakeEmbeddingService:
        def get_active_profile(self, *, text_builder_version: str):
            return SimpleNamespace(profile_id=f"local:{text_builder_version}", model_name="bge-small")

        async def embed_text(self, text: str) -> EmbeddingResult:
            if any(k in text for k in ("爵士", "旋律", "音乐", "night")):
                vec = [1.0, 0.0, 0.0]
            elif any(k in text for k in ("数据库", "迁移", "schema")):
                vec = [0.0, 1.0, 0.0]
            else:
                vec = [0.0, 0.0, 1.0]
            return EmbeddingResult(model_name="bge-small", dimension=3, vector=vec)

        async def embed_texts(self, texts: list[str]) -> list[EmbeddingResult]:
            return [await self.embed_text(text) for text in texts]

    evidence = SimpleNamespace(
        memory=SimpleNamespace(
            memory_operation_guard=guard,
            memory_operation_epoch=lambda: 1,
            embedding_service=_FakeEmbeddingService(),
        ),
        governance_revision=AsyncMock(return_value="r1"),
        recent=AsyncMock(return_value=events),
        last_chat_at=AsyncMock(return_value=0),
        current=AsyncMock(side_effect=lambda _user, ids: [e for e in events if e["event_id"] in ids]),
    )
    drafts = [
        {
            "kind": "perspective",
            "topic": "深夜爵士放松",
            "content": "用户夜间经常借爵士乐舒缓压力。",
            "applicability": "聊到深夜听歌或放松方式时",
            "citations": [{"event_id": "e1", "quote": "深夜循环听爵士乐"}],
        },
        {
            "kind": "open_question",
            "topic": "周末数据库迁移",
            "content": "数据库迁移的窗口安排是否需要提前备份验证。",
            "applicability": "讨论数据库变更计划时",
            "citations": [{"event_id": "e2", "quote": "数据库迁移放到周末"}],
        },
    ]
    service = PersonaJournalService(
        store=ReflectionStore(str(path)),
        evidence=evidence,
        personas=SimpleNamespace(
            get=AsyncMock(return_value=persona),
            get_by_slug=AsyncMock(return_value=persona),
            get_active_id=AsyncMock(return_value="p1"),
        ),
        allow_event=AsyncMock(return_value=True),
        generate=AsyncMock(return_value=json.dumps({"thoughts": drafts}, ensure_ascii=False)),
        verify=AsyncMock(return_value='{"supported": [true, true]}'),
    )
    assert await service.reflect("u1", "p1") == "completed"

    # Cross-wording semantic match ("旋律" does not literally appear in thought text).
    semantic_hits = await service.relevant(
        user_id="u1",
        persona_name="magi",
        query="今晚想放点轻缓旋律",
    )
    assert len(semantic_hits) == 1
    assert "爵士乐" in semantic_hits[0]["content"]

    # Unrelated query yields empty list even with semantic scoring enabled.
    unrelated = await service.relevant(
        user_id="u1",
        persona_name="magi",
        query="tomorrow flight ticket",
    )
    assert unrelated == []

    # Disable embeddings -> jieba/bigram lexical fallback still catches offset Chinese words ("听爵士").
    evidence.memory.embedding_service = None
    lexical_hits = await service.relevant(
        user_id="u1",
        persona_name="magi",
        query="又在听爵士了",
    )
    assert len(lexical_hits) == 1
    assert "爵士乐" in lexical_hits[0]["content"]
