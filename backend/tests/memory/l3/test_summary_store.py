from __future__ import annotations

import asyncio
import time

import pytest

from magi.events.events import Event, EventLevel, EventTypes
from magi.memory.event_contracts import normalize_runtime_event
from magi.memory.l3.models import EpisodicGenerationResult, L3Candidate, ValidationDecision


class _ExperienceSummaryL2Stub:
    def __init__(self, event_ids: list[str] | dict[str, list[str]]) -> None:
        if isinstance(event_ids, dict):
            self._events_by_episode = {key: list(value) for key, value in event_ids.items()}
            self._default_event_ids: list[str] = []
        else:
            self._events_by_episode = {}
            self._default_event_ids = list(event_ids)

    async def list_episode_events(self, *, episode_id: str):
        event_ids = self._events_by_episode.get(episode_id, self._default_event_ids)
        return [{"episode_id": episode_id, "event_id": event_id} for event_id in event_ids]


class _BatchTrackingEmbeddingService:
    def __init__(self) -> None:
        self.single_calls: list[str] = []
        self.batch_calls: list[list[str]] = []

    async def embed_text(self, text: str):
        self.single_calls.append(text)
        return self._make_result(text)

    async def embed_texts(self, texts: list[str]):
        self.batch_calls.append(list(texts))
        return [self._make_result(text) for text in texts]

    def _make_result(self, text: str):
        from magi.memory.embedding.embedding_service import EmbeddingResult

        lowered = text.lower()
        vector = [0.0, 0.0, 0.0, 0.0]
        if "stress" in lowered:
            vector[0] = 1.0
        if "career" in lowered:
            vector[1] = 1.0
        if "summary" in lowered:
            vector[2] = 1.0
        if not any(vector):
            vector[3] = 1.0
        return EmbeddingResult(model_name="test-embedding", dimension=4, vector=vector)

    def result_for_index(self, result, *, text_builder_version: str):
        # Mirror MemoryEmbeddingService.result_for_index; the identity
        # transform is sufficient for these tests.
        return result


class _RecordingVectorIndex:
    def __init__(self) -> None:
        self.upsert_many_calls: list[list[str]] = []
        self.upsert_calls: list[str] = []

    async def upsert_many(self, items: list[dict[str, object]]) -> None:
        self.upsert_many_calls.append([str(item["entity_id"]) for item in items])

    async def upsert(self, *, entity_id: str, embedding, metadata=None) -> None:
        _ = (embedding, metadata)
        self.upsert_calls.append(entity_id)

    async def close(self) -> None:
        return None


class _FetchOnlyL1Stub:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows_by_id = {str(row["event_id"]): dict(row) for row in rows}
        self.calls: list[list[str]] = []

    async def fetch_events(self, event_ids, **_kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(list(event_ids))
        rows = [self.rows_by_id[event_id] for event_id in event_ids if event_id in self.rows_by_id]
        return list(reversed(rows))


@pytest.mark.asyncio
async def test_load_experience_events_fetches_batch_and_preserves_requested_order(tmp_path):
    from magi.memory.l3.summary_store import L3SummaryStore

    l3_store = L3SummaryStore(db_path=str(tmp_path / "memory.db"), vector_enabled=False)
    l1_store = _FetchOnlyL1Stub(
        [
            {"event_id": "evt-a", "timestamp": 1.0, "event_type": "USER_MESSAGE", "content": "A"},
            {"event_id": "evt-b", "timestamp": 2.0, "event_type": "USER_MESSAGE", "content": "B"},
            {"event_id": "evt-c", "timestamp": 3.0, "event_type": "USER_MESSAGE", "content": "C"},
        ]
    )

    events = await l3_store._load_experience_events(
        l1_store=l1_store,
        event_ids=["evt-a", "evt-b", "evt-missing", "evt-c"],
    )

    assert l1_store.calls == [["evt-a", "evt-b", "evt-missing", "evt-c"]]
    assert [event["event_id"] for event in events] == ["evt-a", "evt-b", "evt-c"]


@pytest.mark.asyncio
async def test_generate_episodic_summary_fetches_events_in_one_batch(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    from magi.memory.l3.summary_store import L3SummaryStore

    l3_store = L3SummaryStore(db_path=str(tmp_path / "memory.db"), vector_enabled=False)
    l1_store = _FetchOnlyL1Stub(
        [
            {
                "event_id": "evt-first",
                "timestamp": 10.0,
                "event_type": "USER_MESSAGE",
                "source": "chat",
                "content": "First event",
            },
            {
                "event_id": "evt-second",
                "timestamp": 20.0,
                "event_type": "AI_RESPONSE",
                "source": "chat",
                "content": "Second event",
            },
        ]
    )

    async def _fake_generate(pack, *, fallback_label, fallback_content):  # type: ignore[no-untyped-def]
        _ = fallback_label, fallback_content
        return EpisodicGenerationResult(
            candidate=L3Candidate(
                summary_type="thematic",
                summary_category="episodic",
                content="Generated from fetched batch.",
                source_event_ids=list(pack.source_event_ids),
                insight_metadata={"label": "Fetched batch"},
            ),
            used_fallback=False,
        )

    monkeypatch.setattr(
        l3_store._episodic_llm_service, "generate_episodic_candidate", _fake_generate
    )

    summary = await l3_store.generate_episodic_summary(
        l1_store=l1_store,
        episode={
            "episode_id": "ep-batch",
            "episode_type": "activity",
            "time_start": 10.0,
            "time_end": 20.0,
            "primary_entity_ids": [],
            "primary_topic_keys": [],
        },
        episode_event_ids=["evt-first", "evt-second"],
    )

    assert summary is not None
    assert l1_store.calls == [["evt-first", "evt-second"]]
    assert summary["source_event_ids"] == ["evt-first", "evt-second"]


@pytest.mark.asyncio
async def test_experience_member_events_are_sampled_across_episode_span(tmp_path):
    from magi.memory.l3.summary_store import L3SummaryStore

    l3_store = L3SummaryStore(db_path=str(tmp_path / "memory.db"), vector_enabled=False)
    l2_store = _ExperienceSummaryL2Stub(
        {
            f"ep-{episode_index}": [
                f"evt-{episode_index}-{event_index}" for event_index in range(20)
            ]
            for episode_index in range(8)
        }
    )

    episode_ids, event_ids = await l3_store._collect_experience_member_event_ids(
        l2_store=l2_store,
        experience_members=[
            {"member_type": "episode", "member_id": f"ep-{episode_index}", "role": "core"}
            for episode_index in range(8)
        ],
    )

    assert episode_ids == [f"ep-{index}" for index in range(8)]
    assert len(event_ids) == 30
    for episode_index in range(8):
        assert any(event_id.startswith(f"evt-{episode_index}-") for event_id in event_ids)
    assert "evt-0-0" in event_ids
    assert "evt-7-19" in event_ids


@pytest.mark.asyncio
async def test_l3_summary_excludes_runtime_telemetry_and_keeps_sources(tmp_path):
    from magi.memory.l1.event_store import L1EventStore
    from magi.memory.l3.summary_store import L3SummaryStore

    l1_store = L1EventStore(db_path=str(tmp_path / "l1_events.db"))
    l3_store = L3SummaryStore(db_path=str(tmp_path / "memory.db"))
    await l1_store.initialize()
    await l3_store.initialize()

    chat_event = normalize_runtime_event(
        Event(
            type=EventTypes.USER_MESSAGE,
            data={
                "user_id": "u1",
                "session_id": "s1",
                "content": "I want to switch jobs this year.",
            },
            source="chat",
            level=EventLevel.INFO,
            correlation_id="evt-1",
            timestamp=1710000000.0,
            event_id="evt-1",
        ),
    )
    telemetry_event = normalize_runtime_event(
        Event(
            type=EventTypes.TASK_COMPLETED,
            data={"user_id": "u1", "session_id": "s1", "task_id": "orchestrate"},
            source="runtime",
            level=EventLevel.INFO,
            correlation_id="evt-2",
            timestamp=1710000300.0,
            event_id="evt-2",
        ),
    )

    await l1_store.store(chat_event)
    await l1_store.store(telemetry_event)

    summary = await l3_store.generate_temporal_summary(
        l1_store=l1_store,
        summary_category="day",
        period_start=1709990000.0,
        period_end=1710003600.0,
    )

    assert summary is not None
    assert summary["source_event_count"] == 1
    assert summary["source_event_ids"] == ["evt-1"]
    assert "switch jobs" in summary["content"].lower()
    event_links = await l3_store.list_summary_event_links(summary["summary_id"])
    assert len(event_links) == 1
    assert event_links[0]["event_id"] == "evt-1"
    assert await l1_store.count_events() == 2


@pytest.mark.asyncio
async def test_generate_experience_summary_uses_evidence_when_title_is_untitled(tmp_path):
    from magi.memory.l1.event_store import L1EventStore
    from magi.memory.l3.summary_store import L3SummaryStore

    l1_store = L1EventStore(db_path=str(tmp_path / "l1_events.db"), vector_enabled=False)
    l3_store = L3SummaryStore(db_path=str(tmp_path / "memory.db"), vector_enabled=False)
    await l1_store.initialize()
    await l3_store.initialize()

    gmail_event = normalize_runtime_event(
        Event(
            type=EventTypes.USER_MESSAGE,
            data={
                "user_id": "u1",
                "session_id": "s1",
                "content": "在 Gmail 查看 iKuuu VPN 流量重置通知。",
            },
            source="chat",
            level=EventLevel.INFO,
            correlation_id="evt-gmail",
            timestamp=1710000000.0,
            event_id="evt-gmail",
        )
    )
    discord_event = normalize_runtime_event(
        Event(
            type=EventTypes.USER_MESSAGE,
            data={
                "user_id": "u1",
                "session_id": "s1",
                "content": "随后浏览 Discord announcements 里的 Midjourney 提及。",
            },
            source="chat",
            level=EventLevel.INFO,
            correlation_id="evt-discord",
            timestamp=1710000300.0,
            event_id="evt-discord",
        )
    )
    await l1_store.store(gmail_event)
    await l1_store.store(discord_event)

    summary = await l3_store.generate_experience_summary(
        l1_store=l1_store,
        l2_store=_ExperienceSummaryL2Stub(["evt-gmail", "evt-discord"]),
        experience={
            "experience_id": "exp-untitled",
            "title": "Untitled experience / Untitled exper",
            "intent": "Untitled experience / Untitled exper",
            "magi_interpretation": "Magi grouped related episode evidence into a narratable memory.",
            "time_start": 1710000000.0,
            "time_end": 1710000300.0,
            "primary_entity_ids": ["software:gmail", "software:discord"],
            "primary_topic_keys": ["midjourney"],
        },
        experience_members=[
            {"member_type": "episode", "member_id": "ep-activity", "role": "core"},
        ],
    )

    assert summary is not None
    assert "Untitled" not in summary["insight_metadata"]["label"]
    assert summary["insight_metadata"]["source_experience_id"] == "exp-untitled"
    assert "source_episode_id" not in summary["insight_metadata"]
    assert "Gmail" in summary["content"] or "Discord" in summary["content"]
    assert summary["content"] != "Magi grouped related episode evidence into a narratable memory."


@pytest.mark.asyncio
async def test_generate_experience_summary_ignores_machine_entity_ids_in_label(tmp_path):
    from magi.memory.l1.event_store import L1EventStore
    from magi.memory.l3.summary_store import L3SummaryStore

    l1_store = L1EventStore(db_path=str(tmp_path / "l1_events.db"), vector_enabled=False)
    l3_store = L3SummaryStore(db_path=str(tmp_path / "memory.db"), vector_enabled=False)
    await l1_store.initialize()
    await l3_store.initialize()

    gmail_event = normalize_runtime_event(
        Event(
            type=EventTypes.USER_MESSAGE,
            data={
                "user_id": "u1",
                "session_id": "s1",
                "content": "Chrome 浏览 Gmail 收件箱，并查看一封产品通知。",
            },
            source="chrome_history",
            level=EventLevel.INFO,
            correlation_id="evt-gmail-readable",
            timestamp=1710000000.0,
            event_id="evt-gmail-readable",
        )
    )
    await l1_store.store(gmail_event)

    summary = await l3_store.generate_experience_summary(
        l1_store=l1_store,
        l2_store=_ExperienceSummaryL2Stub(["evt-gmail-readable"]),
        experience={
            "experience_id": "exp-machine-ids",
            "title": "Untitled experience",
            "intent": "Untitled experience",
            "time_start": 1710000000.0,
            "time_end": 1710000300.0,
            "primary_entity_ids": [
                "software:7e4eb50fae61",
                "user:local_user",
                "software:gmail",
            ],
            "primary_topic_keys": ["01KVABCDEF123"],
        },
        experience_members=[
            {"member_type": "episode", "member_id": "ep-machine", "role": "core"},
        ],
    )

    assert summary is not None
    label = summary["insight_metadata"]["label"]
    assert "gmail" in label.lower()
    assert "7e4eb50fae61" not in label.lower()
    assert "local" not in label.lower()
    assert "01KV" not in label


@pytest.mark.asyncio
async def test_generate_experience_summary_marks_llm_candidate(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    from magi.memory.l1.event_store import L1EventStore
    from magi.memory.l3.summary_store import L3SummaryStore

    l1_store = L1EventStore(db_path=str(tmp_path / "l1_events.db"), vector_enabled=False)
    l3_store = L3SummaryStore(db_path=str(tmp_path / "memory.db"), vector_enabled=False)
    await l1_store.initialize()
    await l3_store.initialize()

    event = normalize_runtime_event(
        Event(
            type=EventTypes.USER_MESSAGE,
            data={
                "user_id": "u1",
                "session_id": "s1",
                "content": "在 V2EX 和 Kimi 之间切换，比较 AI 工具。",
            },
            source="chat",
            level=EventLevel.INFO,
            correlation_id="evt-exp-llm",
            timestamp=1710000000.0,
            event_id="evt-exp-llm",
        )
    )
    await l1_store.store(event)

    async def _fake_generate(pack, *, fallback_label, fallback_content):  # type: ignore[no-untyped-def]
        _ = fallback_label, fallback_content
        return EpisodicGenerationResult(
            candidate=L3Candidate(
                summary_type="thematic",
                summary_category="episodic",
                content="这段经历主要是在 V2EX 和 Kimi 之间比较 AI 工具。",
                source_event_ids=list(pack.source_event_ids),
                insight_metadata={"label": "比较 AI 工具"},
            ),
            used_fallback=False,
        )

    monkeypatch.setattr(
        l3_store._episodic_llm_service, "generate_episodic_candidate", _fake_generate
    )

    summary = await l3_store.generate_experience_summary(
        l1_store=l1_store,
        l2_store=_ExperienceSummaryL2Stub(["evt-exp-llm"]),
        experience={
            "experience_id": "exp-llm",
            "title": "AI 工具比较",
            "time_start": 1710000000.0,
            "time_end": 1710000300.0,
            "primary_entity_ids": ["software:v2ex", "software:kimi"],
            "primary_topic_keys": ["ai-tools"],
        },
        experience_members=[
            {"member_type": "episode", "member_id": "ep-llm", "role": "core"},
        ],
    )

    assert summary is not None
    assert summary["generated_by_model"] == "episodic-llm"


@pytest.mark.asyncio
async def test_upsert_candidate_persists_event_and_task_links(tmp_path):
    from magi.memory.l3.summary_store import L3SummaryStore

    l3_store = L3SummaryStore(db_path=str(tmp_path / "memory.db"), vector_enabled=False)
    await l3_store.initialize()

    summary = await l3_store.upsert_candidate(
        candidate=L3Candidate(
            summary_type="insight",
            summary_category="task_reflection",
            content="The user clarified that growth matters more than salary.",
            source_event_ids=["evt-1", "evt-2"],
        ),
        source_task_ids=["task-1"],
    )

    event_links = await l3_store.list_summary_event_links(summary["summary_id"])
    task_links = await l3_store.list_summary_task_links(summary["summary_id"])

    assert {link["event_id"] for link in event_links} == {"evt-1", "evt-2"}
    assert all(link["link_role"] == "primary" for link in event_links)
    assert len(task_links) == 1
    assert task_links[0]["task_id"] == "task-1"
    assert task_links[0]["link_role"] == "source_task"


@pytest.mark.asyncio
async def test_upsert_candidate_merges_existing_insight_key(tmp_path):
    from magi.memory.l3.summary_store import L3SummaryStore

    l3_store = L3SummaryStore(db_path=str(tmp_path / "memory.db"), vector_enabled=False)
    await l3_store.initialize()

    first = await l3_store.upsert_candidate(
        candidate=L3Candidate(
            summary_type="insight",
            summary_category="state_change",
            content="Music preference signal emerged.",
            source_event_ids=["evt-1"],
            insight_key="state_change:user:self:music",
            review_state="pending_confirmation",
            insight_metadata={"kind": "state_change"},
        ),
    )
    second = await l3_store.upsert_candidate(
        candidate=L3Candidate(
            summary_type="insight",
            summary_category="state_change",
            content="Music preference signal emerged with stronger evidence.",
            source_event_ids=["evt-2", "evt-1"],
            insight_key="state_change:user:self:music",
            review_state="pending_confirmation",
            insight_metadata={"kind": "state_change", "policy": "state_change_gate_v1"},
        ),
    )

    assert second["summary_id"] == first["summary_id"]
    assert await l3_store.count_summaries() == 1
    assert second["source_event_ids"] == ["evt-1", "evt-2"]
    assert second["source_event_count"] == 2
    assert second["insight_key"] == "state_change:user:self:music"
    assert second["review_state"] == "pending_confirmation"
    assert second["insight_metadata"]["policy"] == "state_change_gate_v1"
    event_links = await l3_store.list_summary_event_links(second["summary_id"])
    assert {link["event_id"] for link in event_links} == {"evt-1", "evt-2"}


@pytest.mark.asyncio
async def test_count_summaries_can_filter_by_creation_time(tmp_path):
    from magi.memory.l3.summary_store import L3SummaryStore

    l3_store = L3SummaryStore(db_path=str(tmp_path / "memory.db"), vector_enabled=False)
    await l3_store.initialize()

    for summary_id, created_at in [("older", 100.0), ("inside", 200.0), ("newer", 300.0)]:
        await l3_store._store_summary(
            {
                "summary_id": summary_id,
                "summary_type": "thematic",
                "summary_category": "topic",
                "period_start": created_at,
                "period_end": created_at + 10.0,
                "content": f"{summary_id} summary",
                "key_topics": [],
                "key_entities": [],
                "sentiment_summary": None,
                "change_and_pattern": None,
                "source_event_ids": [],
                "source_event_count": 0,
                "importance_aggregate": 0.5,
                "event_type_distribution": {},
                "generated_by_model": "test",
                "generation_prompt": None,
                "generation_reason": "test",
                "created_at": created_at,
                "updated_at": created_at,
            }
        )

    assert await l3_store.count_summaries() == 3
    assert await l3_store.count_summaries(start_time=150.0, end_time=250.0) == 1
    assert await l3_store.count_summaries(start_time=150.0) == 2
    assert await l3_store.count_summaries(end_time=250.0) == 2


@pytest.mark.asyncio
async def test_search_summaries_fuses_bm25_and_vector_hits(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    from magi.memory.l3.summary_store import L3SummaryStore

    l3_store = L3SummaryStore(db_path=str(tmp_path / "memory.db"), vector_enabled=False)
    await l3_store.initialize()

    await l3_store._store_summary(
        {
            "summary_id": "summary-bm25",
            "summary_type": "thematic",
            "summary_category": "topic",
            "period_start": 1.0,
            "period_end": 2.0,
            "content": "remote role planning recap",
            "key_topics": ["job"],
            "key_entities": [],
            "sentiment_summary": None,
            "change_and_pattern": None,
            "source_event_ids": ["evt-1"],
            "source_event_count": 1,
            "importance_aggregate": 0.7,
            "event_type_distribution": {},
            "generated_by_model": "rule-summary",
            "generation_prompt": None,
            "generation_reason": "thematic:topic:job",
            "created_at": 1.0,
            "updated_at": 1.0,
        }
    )
    await l3_store._store_summary(
        {
            "summary_id": "summary-vector",
            "summary_type": "thematic",
            "summary_category": "topic",
            "period_start": 1.0,
            "period_end": 2.0,
            "content": "growth oriented career summary",
            "key_topics": ["career"],
            "key_entities": [],
            "sentiment_summary": None,
            "change_and_pattern": None,
            "source_event_ids": ["evt-2"],
            "source_event_count": 1,
            "importance_aggregate": 0.8,
            "event_type_distribution": {},
            "generated_by_model": "rule-summary",
            "generation_prompt": None,
            "generation_reason": "thematic:topic:career",
            "created_at": 1.0,
            "updated_at": 1.0,
        }
    )

    async def _fake_bm25(
        _query: str,
        *,
        summary_type: str | None = None,
        summary_category: str | None = None,
        limit: int = 20,
    ):  # type: ignore[no-untyped-def]
        _ = summary_type, summary_category, limit
        return [("summary-bm25", -1.0)]

    async def _fake_semantic(
        *,
        query: str,
        summary_type: str | None,
        summary_category: str | None,
        limit: int,
    ):  # type: ignore[no-untyped-def]
        _ = query, summary_type, summary_category, limit
        return [{"summary_id": "summary-vector"}]

    monkeypatch.setattr(l3_store, "bm25_search", _fake_bm25)
    monkeypatch.setattr(l3_store, "vector_search", _fake_semantic)

    results = await l3_store.search_summaries(
        query="career planning", summary_type="thematic", limit=5
    )

    assert [item["summary_id"] for item in results] == ["summary-bm25", "summary-vector"]


@pytest.mark.asyncio
async def test_search_summaries_filters_summary_category(tmp_path, monkeypatch: pytest.MonkeyPatch):
    from magi.memory.l3.summary_store import L3SummaryStore

    l3_store = L3SummaryStore(db_path=str(tmp_path / "memory.db"), vector_enabled=False)
    await l3_store.initialize()

    await l3_store._store_summary(
        {
            "summary_id": "summary-state-change",
            "summary_type": "insight",
            "summary_category": "state_change",
            "period_start": 1.0,
            "period_end": 2.0,
            "content": "stress level remained high across the week",
            "key_topics": ["stress"],
            "key_entities": [],
            "sentiment_summary": None,
            "change_and_pattern": None,
            "source_event_ids": ["evt-1"],
            "source_event_count": 1,
            "importance_aggregate": 0.8,
            "event_type_distribution": {},
            "generated_by_model": "rule-summary",
            "generation_prompt": None,
            "generation_reason": "insight:state_change",
            "created_at": 1.0,
            "updated_at": 1.0,
        }
    )
    await l3_store._store_summary(
        {
            "summary_id": "summary-trend-shift",
            "summary_type": "insight",
            "summary_category": "trend_shift",
            "period_start": 1.0,
            "period_end": 2.0,
            "content": "stress planning shifted toward relief and recovery",
            "key_topics": ["stress"],
            "key_entities": [],
            "sentiment_summary": None,
            "change_and_pattern": None,
            "source_event_ids": ["evt-2"],
            "source_event_count": 1,
            "importance_aggregate": 0.8,
            "event_type_distribution": {},
            "generated_by_model": "rule-summary",
            "generation_prompt": None,
            "generation_reason": "insight:trend_shift",
            "created_at": 1.0,
            "updated_at": 1.0,
        }
    )

    async def _fake_bm25(_query: str, *, summary_type: str | None = None, summary_category: str | None = None, limit: int = 20):  # type: ignore[no-untyped-def]
        _ = summary_type, summary_category, limit
        return [("summary-state-change", -1.0), ("summary-trend-shift", -0.8)]

    async def _fake_semantic(*, query: str, summary_type: str | None, summary_category: str | None, limit: int):  # type: ignore[no-untyped-def]
        _ = query, summary_type, summary_category, limit
        return [{"summary_id": "summary-trend-shift"}, {"summary_id": "summary-state-change"}]

    monkeypatch.setattr(l3_store, "bm25_search", _fake_bm25)
    monkeypatch.setattr(l3_store, "vector_search", _fake_semantic)

    results = await l3_store.search_summaries(
        query="stress",
        summary_type="insight",
        summary_category="state_change",
        limit=5,
    )

    assert [item["summary_id"] for item in results] == ["summary-state-change"]


@pytest.mark.asyncio
async def test_generate_temporal_summary_uses_llm_candidate_when_available(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    from magi.memory.l1.event_store import L1EventStore
    from magi.memory.l3.summary_store import L3SummaryStore

    l1_store = L1EventStore(db_path=str(tmp_path / "l1_events.db"))
    l3_store = L3SummaryStore(db_path=str(tmp_path / "memory.db"), vector_enabled=False)
    await l1_store.initialize()
    await l3_store.initialize()

    chat_event = normalize_runtime_event(
        Event(
            type=EventTypes.USER_MESSAGE,
            data={
                "user_id": "u1",
                "session_id": "s1",
                "content": "I want to switch jobs this year.",
            },
            source="chat",
            level=EventLevel.INFO,
            correlation_id="evt-1",
            timestamp=1710000000.0,
            event_id="evt-1",
        ),
    )
    ai_event = normalize_runtime_event(
        Event(
            type=EventTypes.AI_RESPONSE,
            data={
                "user_id": "u1",
                "session_id": "s1",
                "content": "You should compare growth and salary tradeoffs.",
            },
            source="chat",
            level=EventLevel.INFO,
            correlation_id="evt-2",
            timestamp=1710000300.0,
            event_id="evt-2",
        ),
    )
    await l1_store.store(chat_event)
    await l1_store.store(ai_event)

    async def _fake_prose_model(_pack, **_kwargs):  # type: ignore[no-untyped-def]
        return "LLM rewritten temporal summary"

    async def _fake_structure_model(_pack, *, prose_content, **_kwargs):  # type: ignore[no-untyped-def]
        assert prose_content == "LLM rewritten temporal summary"
        return {
            "key_topics": ["job_search"],
            "change_and_pattern": {
                "changes": ["moved from exploration to planning"],
                "patterns": [],
            },
            "importance_aggregate": 0.9,
        }

    monkeypatch.setattr(
        l3_store._temporal_llm_service, "_call_temporal_prose_model", _fake_prose_model
    )
    monkeypatch.setattr(
        l3_store._temporal_llm_service, "_call_temporal_structure_model", _fake_structure_model
    )

    summary = await l3_store.generate_temporal_summary(
        l1_store=l1_store,
        summary_category="day",
        period_start=1709990000.0,
        period_end=1710003600.0,
    )

    assert summary is not None
    assert summary["content"] == "LLM rewritten temporal summary"
    assert summary["key_topics"] == ["job_search"]
    assert summary["change_and_pattern"] == {
        "changes": ["moved from exploration to planning"],
        "patterns": [],
    }
    assert summary["generated_by_model"] == "temporal-llm"
    event_links = await l3_store.list_summary_event_links(summary["summary_id"])
    assert len(event_links) == 2


@pytest.mark.asyncio
async def test_generate_temporal_summary_includes_period_context(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    from magi.memory.l1.event_store import L1EventStore
    from magi.memory.l3.summary_store import L3SummaryStore

    l1_store = L1EventStore(db_path=str(tmp_path / "l1_events.db"))
    l3_store = L3SummaryStore(db_path=str(tmp_path / "memory.db"), vector_enabled=False)
    await l1_store.initialize()
    await l3_store.initialize()

    await l3_store.upsert_candidate(
        candidate=L3Candidate(
            summary_type="temporal",
            summary_category="month",
            content="The previous month stayed exploratory.",
            source_event_ids=[],
        ),
        summary_overrides={
            "summary_id": "summary-prev-month",
            "summary_type": "temporal",
            "summary_category": "month",
            "period_start": 200.0,
            "period_end": 300.0,
            "key_topics": ["exploration"],
            "generated_by_model": "temporal-llm",
        },
    )
    await l3_store.upsert_candidate(
        candidate=L3Candidate(
            summary_type="temporal",
            summary_category="week",
            content="The first week focused on portfolio execution.",
            source_event_ids=[],
        ),
        summary_overrides={
            "summary_id": "summary-child-week",
            "summary_type": "temporal",
            "summary_category": "week",
            "period_start": 310.0,
            "period_end": 330.0,
            "key_topics": ["portfolio"],
            "generated_by_model": "temporal-llm",
        },
    )

    await l1_store.store(
        normalize_runtime_event(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={
                    "user_id": "u1",
                    "session_id": "s1",
                    "content": "This month I started building the portfolio.",
                },
                source="chat",
                level=EventLevel.INFO,
                correlation_id="evt-current-1",
                timestamp=320.0,
                event_id="evt-current-1",
            ),
        )
    )
    await l1_store.store(
        normalize_runtime_event(
            Event(
                type=EventTypes.AI_RESPONSE,
                data={
                    "user_id": "u1",
                    "session_id": "s1",
                    "content": "The work moved from exploration into execution.",
                },
                source="chat",
                level=EventLevel.INFO,
                correlation_id="evt-current-2",
                timestamp=325.0,
                event_id="evt-current-2",
            ),
        )
    )
    captured: dict[str, object] = {}

    async def _fake_prose_model(pack, **_kwargs):  # type: ignore[no-untyped-def]
        captured["previous"] = list(pack.previous_period_summaries)
        captured["children"] = list(pack.child_period_summaries)
        return "The month shifted from exploration toward portfolio execution."

    async def _fake_structure_model(_pack, *, prose_content, **_kwargs):  # type: ignore[no-untyped-def]
        assert prose_content == "The month shifted from exploration toward portfolio execution."
        return {
            "key_topics": ["portfolio"],
            "change_and_pattern": {
                "changes": ["exploration shifted toward execution"],
                "patterns": [],
            },
        }

    monkeypatch.setattr(
        l3_store._temporal_llm_service, "_call_temporal_prose_model", _fake_prose_model
    )
    monkeypatch.setattr(
        l3_store._temporal_llm_service, "_call_temporal_structure_model", _fake_structure_model
    )

    summary = await l3_store.generate_temporal_summary(
        l1_store=l1_store,
        summary_category="month",
        period_start=300.0,
        period_end=400.0,
    )

    assert summary is not None
    previous = captured["previous"]
    children = captured["children"]
    assert isinstance(previous, list)
    assert isinstance(children, list)
    assert previous[0]["summary_id"] == "summary-prev-month"
    assert children[0]["summary_id"] == "summary-child-week"


@pytest.mark.asyncio
async def test_generate_temporal_summary_falls_back_when_llm_disabled(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    from magi.memory.l1.event_store import L1EventStore
    from magi.memory.l3.summary_store import L3SummaryStore

    l1_store = L1EventStore(db_path=str(tmp_path / "l1_events.db"))
    l3_store = L3SummaryStore(
        db_path=str(tmp_path / "memory.db"),
        vector_enabled=False,
        enable_temporal_llm_summary=False,
    )
    await l1_store.initialize()
    await l3_store.initialize()

    chat_event = normalize_runtime_event(
        Event(
            type=EventTypes.USER_MESSAGE,
            data={
                "user_id": "u1",
                "session_id": "s1",
                "content": "I want to switch jobs this year.",
            },
            source="chat",
            level=EventLevel.INFO,
            correlation_id="evt-1",
            timestamp=1710000000.0,
            event_id="evt-1",
        ),
    )
    ai_event = normalize_runtime_event(
        Event(
            type=EventTypes.AI_RESPONSE,
            data={
                "user_id": "u1",
                "session_id": "s1",
                "content": "You should compare growth and salary tradeoffs.",
            },
            source="chat",
            level=EventLevel.INFO,
            correlation_id="evt-2",
            timestamp=1710000300.0,
            event_id="evt-2",
        ),
    )
    await l1_store.store(chat_event)
    await l1_store.store(ai_event)

    async def _unexpected_model(_pack):  # type: ignore[no-untyped-def]
        raise AssertionError("LLM path should be disabled")

    monkeypatch.setattr(
        l3_store._temporal_llm_service, "_call_temporal_prose_model", _unexpected_model
    )

    summary = await l3_store.generate_temporal_summary(
        l1_store=l1_store,
        summary_category="day",
        period_start=1709990000.0,
        period_end=1710003600.0,
    )

    assert summary is not None
    assert "switch jobs" in summary["content"].lower()
    assert summary["generated_by_model"] == "rule-summary"


@pytest.mark.asyncio
async def test_generate_temporal_summary_includes_plugin_summary_features(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    from magi.memory.l1.event_store import L1EventStore
    from magi.memory.l3.summary_store import L3SummaryStore

    l1_store = L1EventStore(db_path=str(tmp_path / "l1_events.db"))
    l3_store = L3SummaryStore(
        db_path=str(tmp_path / "memory.db"),
        vector_enabled=False,
        temporal_summary_features_builder=lambda **_: {
            "chrome_history": {
                "feature_type": "chrome_history",
                "summary_lines": [
                    "Browsing concentrated heavily on openai.com.",
                    "Repeated visits clustered around openai.com.",
                    "Browsing stayed within a small set of sites.",
                ],
                "focus_domain": "openai.com",
                "focus_share": 0.667,
                "session_count": 1,
                "top_domains": [
                    {"domain": "openai.com", "count": 2},
                    {"domain": "github.com", "count": 1},
                ],
            }
        },
    )
    await l1_store.initialize()
    await l3_store.initialize()

    await l1_store.store(
        normalize_runtime_event(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={
                    "user_id": "u1",
                    "session_id": "s1",
                    "content": "openai.com docs and github.com issues",
                },
                source="chrome_history",
                level=EventLevel.INFO,
                correlation_id="evt-1",
                timestamp=1710000000.0,
                event_id="evt-1",
            ),
        )
    )
    await l1_store.store(
        normalize_runtime_event(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={"user_id": "u1", "session_id": "s1", "content": "Another openai.com visit"},
                source="chrome_history",
                level=EventLevel.INFO,
                correlation_id="evt-2",
                timestamp=1710000300.0,
                event_id="evt-2",
            ),
        )
    )

    captured_features: dict[str, object] = {}

    async def _fake_prose_model(pack, **_kwargs):  # type: ignore[no-untyped-def]
        captured_features.update(pack.plugin_summary_features)
        return "LLM rewritten temporal summary"

    async def _fake_structure_model(_pack, *, prose_content, **_kwargs):  # type: ignore[no-untyped-def]
        assert prose_content == "LLM rewritten temporal summary"
        return {
            "key_topics": ["browsing"],
            "importance_aggregate": 0.7,
        }

    monkeypatch.setattr(
        l3_store._temporal_llm_service, "_call_temporal_prose_model", _fake_prose_model
    )
    monkeypatch.setattr(
        l3_store._temporal_llm_service, "_call_temporal_structure_model", _fake_structure_model
    )

    summary = await l3_store.generate_temporal_summary(
        l1_store=l1_store,
        summary_category="day",
        period_start=1709990000.0,
        period_end=1710003600.0,
    )

    assert summary is not None
    assert summary["content"] == "LLM rewritten temporal summary"
    assert captured_features == {
        "chrome_history": {
            "feature_type": "chrome_history",
            "summary_lines": [
                "Browsing concentrated heavily on openai.com.",
                "Repeated visits clustered around openai.com.",
                "Browsing stayed within a small set of sites.",
            ],
            "focus_domain": "openai.com",
            "focus_share": 0.667,
            "session_count": 1,
            "top_domains": [
                {"domain": "openai.com", "count": 2},
                {"domain": "github.com", "count": 1},
            ],
        }
    }


@pytest.mark.asyncio
async def test_generate_temporal_summary_uses_plugin_summary_lines_in_fallback(tmp_path):
    from magi.memory.l1.event_store import L1EventStore
    from magi.memory.l3.summary_store import L3SummaryStore

    l1_store = L1EventStore(db_path=str(tmp_path / "l1_events.db"))
    l3_store = L3SummaryStore(
        db_path=str(tmp_path / "memory.db"),
        vector_enabled=False,
        enable_temporal_llm_summary=False,
        temporal_summary_features_builder=lambda **_: {
            "chrome_history": {
                "feature_type": "chrome_history",
                "summary_lines": [
                    "Browsing concentrated heavily on openai.com.",
                ],
            }
        },
    )
    await l1_store.initialize()
    await l3_store.initialize()

    await l1_store.store(
        normalize_runtime_event(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={
                    "user_id": "u1",
                    "session_id": "s1",
                    "content": "openai.com docs and github.com issues",
                },
                source="chrome_history",
                level=EventLevel.INFO,
                correlation_id="evt-1",
                timestamp=1710000000.0,
                event_id="evt-1",
            ),
        )
    )
    await l1_store.store(
        normalize_runtime_event(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={"user_id": "u1", "session_id": "s1", "content": "Another openai.com visit"},
                source="chrome_history",
                level=EventLevel.INFO,
                correlation_id="evt-2",
                timestamp=1710000300.0,
                event_id="evt-2",
            ),
        )
    )

    summary = await l3_store.generate_temporal_summary(
        l1_store=l1_store,
        summary_category="day",
        period_start=1709990000.0,
        period_end=1710003600.0,
    )

    assert summary is not None
    assert "Browsing concentrated heavily on openai.com." in summary["content"]


@pytest.mark.asyncio
async def test_generate_temporal_summary_uses_source_aware_compaction(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    from magi.memory.l1.event_store import L1EventStore
    from magi.memory.l3.summary_store import L3SummaryStore

    l1_store = L1EventStore(db_path=str(tmp_path / "l1_events.db"))
    l3_store = L3SummaryStore(db_path=str(tmp_path / "memory.db"), vector_enabled=False)
    await l1_store.initialize()
    await l3_store.initialize()

    for index in range(160):
        await l1_store.store(
            normalize_runtime_event(
                Event(
                    type=EventTypes.USER_MESSAGE,
                    data={"user_id": "u1", "session_id": "s1", "content": f"Chrome visit {index}"},
                    source="chrome_history",
                    level=EventLevel.INFO,
                    correlation_id=f"chrome-{index}",
                    timestamp=1710001000.0 + index,
                    event_id=f"chrome-{index}",
                ),
            )
        )
    for index in range(2):
        await l1_store.store(
            normalize_runtime_event(
                Event(
                    type=EventTypes.USER_MESSAGE,
                    data={"user_id": "u1", "session_id": "s1", "content": f"Netease track {index}"},
                    source="netease_music",
                    level=EventLevel.INFO,
                    correlation_id=f"music-{index}",
                    timestamp=1710000000.0 + index,
                    event_id=f"music-{index}",
                ),
            )
        )

    captured_pack = None

    async def _fake_prose_model(pack, **_kwargs):  # type: ignore[no-untyped-def]
        nonlocal captured_pack
        captured_pack = pack
        return "Balanced temporal summary"

    async def _fake_structure_model(_pack, *, prose_content, **_kwargs):  # type: ignore[no-untyped-def]
        assert prose_content == "Balanced temporal summary"
        return {
            "key_topics": ["browsing", "music"],
            "importance_aggregate": 0.7,
        }

    monkeypatch.setattr(
        l3_store._temporal_llm_service, "_call_temporal_prose_model", _fake_prose_model
    )
    monkeypatch.setattr(
        l3_store._temporal_llm_service, "_call_temporal_structure_model", _fake_structure_model
    )

    summary = await l3_store.generate_temporal_summary(
        l1_store=l1_store,
        summary_category="day",
        period_start=1709999000.0,
        period_end=1710002000.0,
    )

    assert summary is not None
    assert captured_pack is not None
    assert captured_pack.window_event_count == 162
    assert captured_pack.source_event_count <= 120
    assert captured_pack.omitted_event_count == 162 - captured_pack.source_event_count
    assert captured_pack.source_distribution["chrome_history"]["total_event_count"] == 160
    assert captured_pack.source_distribution["netease_music"]["total_event_count"] == 2
    assert {"music-0", "music-1"}.issubset(set(captured_pack.source_event_ids))
    assert summary["evidence_selection"]["omitted_event_count"] > 0


@pytest.mark.asyncio
async def test_generate_temporal_summary_falls_back_when_llm_candidate_is_rejected(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    from magi.memory.l1.event_store import L1EventStore
    from magi.memory.l3 import summary_store as summary_store_module
    from magi.memory.l3.summary_store import L3SummaryStore

    l1_store = L1EventStore(db_path=str(tmp_path / "l1_events.db"))
    l3_store = L3SummaryStore(db_path=str(tmp_path / "memory.db"), vector_enabled=False)
    await l1_store.initialize()
    await l3_store.initialize()

    chat_event = normalize_runtime_event(
        Event(
            type=EventTypes.USER_MESSAGE,
            data={
                "user_id": "u1",
                "session_id": "s1",
                "content": "I want to switch jobs this year.",
            },
            source="chat",
            level=EventLevel.INFO,
            correlation_id="evt-1",
            timestamp=1710000000.0,
            event_id="evt-1",
        ),
    )
    ai_event = normalize_runtime_event(
        Event(
            type=EventTypes.AI_RESPONSE,
            data={
                "user_id": "u1",
                "session_id": "s1",
                "content": "You should compare growth and salary tradeoffs.",
            },
            source="chat",
            level=EventLevel.INFO,
            correlation_id="evt-2",
            timestamp=1710000300.0,
            event_id="evt-2",
        ),
    )
    await l1_store.store(chat_event)
    await l1_store.store(ai_event)

    async def _fake_prose_model(_pack, **_kwargs):  # type: ignore[no-untyped-def]
        return "LLM rewritten temporal summary"

    async def _fake_structure_model(_pack, *, prose_content, **_kwargs):  # type: ignore[no-untyped-def]
        assert prose_content == "LLM rewritten temporal summary"
        return {
            "key_topics": ["job_search"],
            "importance_aggregate": 0.9,
        }

    def _fake_validate(candidate, *, evidence_events, task_outcome=None):  # type: ignore[no-untyped-def]
        _ = evidence_events, task_outcome
        if candidate.content == "LLM rewritten temporal summary":
            return ValidationDecision(action="reject", reason="synthetic_rejection")
        return ValidationDecision(action="accept", reason="accepted")

    monkeypatch.setattr(
        l3_store._temporal_llm_service, "_call_temporal_prose_model", _fake_prose_model
    )
    monkeypatch.setattr(
        l3_store._temporal_llm_service, "_call_temporal_structure_model", _fake_structure_model
    )
    monkeypatch.setattr(summary_store_module, "validate_candidate", _fake_validate)

    summary = await l3_store.generate_temporal_summary(
        l1_store=l1_store,
        summary_category="day",
        period_start=1709990000.0,
        period_end=1710003600.0,
    )

    assert summary is not None
    assert "switch jobs" in summary["content"].lower()
    assert summary["generated_by_model"] == "rule-summary"


@pytest.mark.asyncio
async def test_generate_thematic_summary_groups_topic_events_and_links_sources(tmp_path):
    from magi.memory.l1.event_store import L1EventStore
    from magi.memory.l3.summary_store import L3SummaryStore

    l1_store = L1EventStore(db_path=str(tmp_path / "l1_events.db"))
    l3_store = L3SummaryStore(db_path=str(tmp_path / "memory.db"), vector_enabled=False)
    await l1_store.initialize()
    await l3_store.initialize()

    await l1_store.store(
        normalize_runtime_event(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={
                    "user_id": "u1",
                    "session_id": "s1",
                    "content": "I want to switch jobs this year.",
                },
                source="chat",
                level=EventLevel.INFO,
                correlation_id="evt-1",
                timestamp=1710000000.0,
                event_id="evt-1",
            ),
        )
    )
    await l1_store.store(
        normalize_runtime_event(
            Event(
                type=EventTypes.AI_RESPONSE,
                data={
                    "user_id": "u1",
                    "session_id": "s1",
                    "content": "The job market looks stronger for remote roles.",
                },
                source="chat",
                level=EventLevel.INFO,
                correlation_id="evt-2",
                timestamp=1710000300.0,
                event_id="evt-2",
            ),
        )
    )
    await l1_store.store(
        normalize_runtime_event(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={
                    "user_id": "u1",
                    "session_id": "s1",
                    "content": "I should finish my portfolio first.",
                },
                source="chat",
                level=EventLevel.INFO,
                correlation_id="evt-3",
                timestamp=1710000600.0,
                event_id="evt-3",
            ),
        )
    )

    summary = await l3_store.generate_thematic_summary(
        l1_store=l1_store,
        topic="job",
        min_source_count=2,
    )

    assert summary is not None
    assert summary["summary_type"] == "thematic"
    assert summary["summary_category"] == "topic"
    assert summary["key_topics"] == ["job"]
    assert summary["source_event_ids"] == ["evt-2", "evt-1"]
    assert summary["generated_by_model"] == "rule-summary"
    event_links = await l3_store.list_summary_event_links(summary["summary_id"])
    assert {link["event_id"] for link in event_links} == {"evt-1", "evt-2"}


@pytest.mark.asyncio
async def test_generate_thematic_summary_uses_llm_candidate_when_available(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    from magi.memory.l1.event_store import L1EventStore
    from magi.memory.l3.summary_store import L3SummaryStore

    l1_store = L1EventStore(db_path=str(tmp_path / "l1_events.db"))
    l3_store = L3SummaryStore(db_path=str(tmp_path / "memory.db"), vector_enabled=False)
    await l1_store.initialize()
    await l3_store.initialize()

    await l1_store.store(
        normalize_runtime_event(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={
                    "user_id": "u1",
                    "session_id": "s1",
                    "content": "I want to switch jobs this year.",
                },
                source="chat",
                level=EventLevel.INFO,
                correlation_id="evt-1",
                timestamp=1710000000.0,
                event_id="evt-1",
            ),
        )
    )
    await l1_store.store(
        normalize_runtime_event(
            Event(
                type=EventTypes.AI_RESPONSE,
                data={
                    "user_id": "u1",
                    "session_id": "s1",
                    "content": "The job market looks stronger for remote roles.",
                },
                source="chat",
                level=EventLevel.INFO,
                correlation_id="evt-2",
                timestamp=1710000300.0,
                event_id="evt-2",
            ),
        )
    )

    async def _fake_prose_model(_pack):  # type: ignore[no-untyped-def]
        return "Job-switch planning kept centering on remote opportunities."

    async def _fake_structure_model(_pack, *, prose_content):  # type: ignore[no-untyped-def]
        assert prose_content == "Job-switch planning kept centering on remote opportunities."
        return {
            "key_topics": ["job_search", "remote_roles"],
            "importance_aggregate": 0.88,
        }

    monkeypatch.setattr(l3_store._topic_llm_service, "_call_topic_prose_model", _fake_prose_model)
    monkeypatch.setattr(
        l3_store._topic_llm_service, "_call_topic_structure_model", _fake_structure_model
    )

    summary = await l3_store.generate_thematic_summary(
        l1_store=l1_store,
        topic="job",
        min_source_count=2,
    )

    assert summary is not None
    assert summary["summary_type"] == "thematic"
    assert summary["summary_category"] == "topic"
    assert summary["generated_by_model"] == "topic-llm"
    assert summary["content"] == "Job-switch planning kept centering on remote opportunities."
    assert summary["key_topics"] == ["job_search", "remote_roles"]


@pytest.mark.asyncio
async def test_l3_async_embeddings_flush_full_batches_via_batch_api(tmp_path):
    from magi.memory.l3.summary_store import L3SummaryStore

    embedding_service = _BatchTrackingEmbeddingService()
    store = L3SummaryStore(
        db_path=str(tmp_path / "memory.db"),
        embedding_service=embedding_service,
        async_embeddings=True,
    )
    store._embedding_batch_wait_seconds = 5.0
    await store.initialize()

    try:
        for idx in range(5):
            await store._store_summary(
                {
                    "summary_id": f"summary-batch-{idx}",
                    "summary_type": "thematic",
                    "summary_category": "topic",
                    "period_start": 1.0,
                    "period_end": 2.0,
                    "content": f"career summary {idx}",
                    "key_topics": ["career"],
                    "key_entities": [],
                    "sentiment_summary": None,
                    "change_and_pattern": None,
                    "source_event_ids": [f"evt-{idx}"],
                    "source_event_count": 1,
                    "importance_aggregate": 0.7,
                    "event_type_distribution": {},
                    "generated_by_model": "rule-summary",
                    "generation_prompt": None,
                    "generation_reason": "thematic:topic:career",
                    "created_at": 1.0,
                    "updated_at": 1.0,
                }
            )

        assert store._embedding_queue is not None
        await asyncio.wait_for(store._embedding_queue.join(), timeout=2.0)
    finally:
        await store.shutdown()

    assert embedding_service.single_calls == []
    assert len(embedding_service.batch_calls) == 1
    assert len(embedding_service.batch_calls[0]) == 5


@pytest.mark.asyncio
async def test_l3_async_embeddings_flush_partial_batches_after_timeout(tmp_path):
    from magi.memory.l3.summary_store import L3SummaryStore

    embedding_service = _BatchTrackingEmbeddingService()
    store = L3SummaryStore(
        db_path=str(tmp_path / "memory.db"),
        embedding_service=embedding_service,
        async_embeddings=True,
    )
    store._embedding_batch_wait_seconds = 0.05
    await store.initialize()

    started_at = time.monotonic()
    try:
        for idx in range(2):
            await store._store_summary(
                {
                    "summary_id": f"summary-timeout-{idx}",
                    "summary_type": "thematic",
                    "summary_category": "topic",
                    "period_start": 1.0,
                    "period_end": 2.0,
                    "content": f"stress summary {idx}",
                    "key_topics": ["stress"],
                    "key_entities": [],
                    "sentiment_summary": None,
                    "change_and_pattern": None,
                    "source_event_ids": [f"evt-timeout-{idx}"],
                    "source_event_count": 1,
                    "importance_aggregate": 0.7,
                    "event_type_distribution": {},
                    "generated_by_model": "rule-summary",
                    "generation_prompt": None,
                    "generation_reason": "thematic:topic:stress",
                    "created_at": 1.0,
                    "updated_at": 1.0,
                }
            )

        assert store._embedding_queue is not None
        await asyncio.wait_for(store._embedding_queue.join(), timeout=1.0)
    finally:
        await store.shutdown()

    assert time.monotonic() - started_at >= 0.04
    assert embedding_service.single_calls == []
    assert [[text.split("\n")[0] for text in batch] for batch in embedding_service.batch_calls] == [
        ["stress summary 0", "stress summary 1"]
    ]


@pytest.mark.asyncio
async def test_l3_batch_embedding_flush_indexes_summary_chunks(tmp_path):
    from magi.memory.l3.summary_store import L3SummaryStore

    embedding_service = _BatchTrackingEmbeddingService()
    store = L3SummaryStore(
        db_path=str(tmp_path / "memory.db"),
        embedding_service=embedding_service,
        async_embeddings=False,
    )
    await store.initialize()
    recording_index = _RecordingVectorIndex()
    store._vector_index = recording_index  # type: ignore[assignment]
    store._schedule_summary_embedding = lambda summary: asyncio.sleep(0)  # type: ignore[method-assign]

    summary = {
        "summary_id": "summary-chunked",
        "summary_type": "thematic",
        "summary_category": "topic",
        "period_start": 1.0,
        "period_end": 2.0,
        "content": (
            "career planning summary block one " * 20
            + "career planning summary block two " * 20
            + "career planning summary block three " * 20
        ),
        "key_topics": ["career"],
        "key_entities": [],
        "sentiment_summary": None,
        "change_and_pattern": None,
        "source_event_ids": ["evt-1"],
        "source_event_count": 1,
        "importance_aggregate": 0.8,
        "event_type_distribution": {},
        "generated_by_model": "rule-summary",
        "generation_prompt": None,
        "generation_reason": "thematic:topic:career",
        "created_at": 1.0,
        "updated_at": 1.0,
    }

    try:
        await store._store_summary(summary)
        await store._maybe_upsert_summary_embeddings([summary])
        results = await store.fetch_by_ids(
            ["summary-chunked"], summary_type=None, summary_category=None
        )
    finally:
        await store.shutdown()

    assert len(recording_index.upsert_many_calls) == 1
    assert all(
        chunk_id.startswith("summary-chunked::chunk-")
        for chunk_id in recording_index.upsert_many_calls[0]
    )
    assert results[0]["embedding_chunk_count"] > 1


@pytest.mark.asyncio
async def test_l3_summary_exposes_embedding_status_and_profile_id(tmp_path):
    from magi.memory.l3.summary_store import L3SummaryStore

    embedding_service = _BatchTrackingEmbeddingService()
    store = L3SummaryStore(
        db_path=str(tmp_path / "memory.db"),
        embedding_service=embedding_service,
        async_embeddings=False,
    )
    await store.initialize()
    try:
        summary = {
            "summary_id": "summary-status",
            "summary_type": "thematic",
            "summary_category": "topic",
            "period_start": 1.0,
            "period_end": 2.0,
            "content": "career summary with embedding status",
            "key_topics": ["career"],
            "key_entities": [],
            "sentiment_summary": None,
            "change_and_pattern": None,
            "source_event_ids": ["evt-1"],
            "source_event_count": 1,
            "importance_aggregate": 0.8,
            "event_type_distribution": {},
            "generated_by_model": "rule-summary",
            "generation_prompt": None,
            "generation_reason": "thematic:topic:career",
            "created_at": 1.0,
            "updated_at": 1.0,
        }
        await store._store_summary(summary)
        await store._maybe_upsert_summary_embeddings([summary])
        results = await store.fetch_by_ids(
            ["summary-status"], summary_type=None, summary_category=None
        )
    finally:
        await store.shutdown()

    assert results[0]["embedding_status"] == "ready"
    assert results[0]["embedding_profile_id"] is not None


@pytest.mark.asyncio
async def test_l3_semantic_search_folds_chunk_hits_to_parent_summary(tmp_path):
    from magi.memory.l3.summary_store import L3SummaryStore
    from magi.memory.embedding.sqlite_vec_index import VectorSearchHit

    embedding_service = _BatchTrackingEmbeddingService()
    store = L3SummaryStore(
        db_path=str(tmp_path / "memory.db"),
        embedding_service=embedding_service,
        async_embeddings=False,
    )
    await store.initialize()
    try:
        summary = {
            "summary_id": "summary-ranked",
            "summary_type": "thematic",
            "summary_category": "topic",
            "period_start": 1.0,
            "period_end": 2.0,
            "content": (
                "career planning summary block one " * 18 + "recovery summary block two " * 18
            ),
            "key_topics": ["career"],
            "key_entities": [],
            "sentiment_summary": None,
            "change_and_pattern": None,
            "source_event_ids": ["evt-1"],
            "source_event_count": 1,
            "importance_aggregate": 0.8,
            "event_type_distribution": {},
            "generated_by_model": "rule-summary",
            "generation_prompt": None,
            "generation_reason": "thematic:topic:career",
            "created_at": 1.0,
            "updated_at": 1.0,
        }
        await store._store_summary(summary)
        await store._maybe_upsert_summary_embeddings([summary])

        async def _fake_search(*, embedding, limit: int, max_distance=None):  # type: ignore[no-untyped-def]
            _ = (embedding, limit, max_distance)
            return [
                VectorSearchHit(entity_id="summary-ranked::chunk-1", distance=0.04),
                VectorSearchHit(entity_id="summary-ranked::chunk-0", distance=0.08),
            ]

        store._vector_index.search = _fake_search  # type: ignore[method-assign]
        ranked = await store.vector_search(
            query="career recovery summary",
            summary_type="thematic",
            summary_category="topic",
            limit=5,
        )
    finally:
        await store.shutdown()

    assert [item["summary_id"] for item in ranked] == ["summary-ranked"]
    assert ranked[0]["distance"] == 0.04
    assert [chunk["chunk_id"] for chunk in ranked[0]["matched_chunks"]] == [
        "summary-ranked::chunk-1",
        "summary-ranked::chunk-0",
    ]


@pytest.mark.asyncio
async def test_l3_rebuild_embeddings_reindexes_disabled_summaries(tmp_path):
    from magi.memory.l3.summary_store import L3SummaryStore

    disabled_store = L3SummaryStore(db_path=str(tmp_path / "memory.db"), vector_enabled=False)
    await disabled_store.initialize()
    try:
        await disabled_store._store_summary(
            {
                "summary_id": "summary-rebuild",
                "summary_type": "thematic",
                "summary_category": "topic",
                "period_start": 1.0,
                "period_end": 2.0,
                "content": "career summary that should be rebuilt",
                "key_topics": ["career"],
                "key_entities": [],
                "sentiment_summary": None,
                "change_and_pattern": None,
                "source_event_ids": ["evt-1"],
                "source_event_count": 1,
                "importance_aggregate": 0.8,
                "event_type_distribution": {},
                "generated_by_model": "rule-summary",
                "generation_prompt": None,
                "generation_reason": "thematic:topic:career",
                "created_at": 1.0,
                "updated_at": 1.0,
            }
        )
    finally:
        await disabled_store.shutdown()

    rebuild_store = L3SummaryStore(
        db_path=str(tmp_path / "memory.db"),
        embedding_service=_BatchTrackingEmbeddingService(),
        async_embeddings=False,
    )
    await rebuild_store.initialize()
    try:
        processed = await rebuild_store.rebuild_embeddings(batch_size=10)
        results = await rebuild_store.fetch_by_ids(
            ["summary-rebuild"],
            summary_type=None,
            summary_category=None,
        )
    finally:
        await rebuild_store.shutdown()

    assert processed == 1
    assert results[0]["embedding_status"] == "ready"
    assert results[0]["embedding_profile_id"] is not None
    assert results[0]["embedding_chunk_count"] > 0
    assert results[0]["last_embedded_at"] is not None
