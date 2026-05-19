"""Tests for DiaryNarrativeOrchestrator (end-to-end with stubbed LLM)."""

from __future__ import annotations

import pytest

from magi.memory.l2.store import L2CognitionStore
from magi.memory.l3.summary_store import L3SummaryStore
from magi.timeline.narrative.orchestrator import DiaryNarrativeOrchestrator
from magi.timeline.narrative.output_schema import DiaryNarrativeOutput, DiarySliceNarrative


class _StubClient:
    def __init__(self, output: DiaryNarrativeOutput) -> None:
        self._output = output
        self.calls: list[dict] = []

    async def generate(self, **kwargs) -> DiaryNarrativeOutput:
        self.calls.append(kwargs)
        return self._output


class _StubL1Store:
    """Returns a fixed list of L1 events regardless of time bounds.

    Used to verify the orchestrator forwards excerpts to the LLM client.
    """

    def __init__(self, events_by_window: dict[tuple[float, float], list[dict]] | None = None,
                 default_events: list[dict] | None = None) -> None:
        self._events_by_window = events_by_window or {}
        self._default = default_events or []
        self.calls: list[dict] = []

    async def query_events(self, **kwargs) -> list[dict]:
        self.calls.append(kwargs)
        start = float(kwargs.get("start_time") or 0.0)
        end = float(kwargs.get("end_time") or 0.0)
        return self._events_by_window.get((start, end), self._default)


@pytest.mark.asyncio
async def test_generate_for_window_writes_essence_to_l3_and_narratives_to_l2(
    l2_store_with_schema: L2CognitionStore,
):
    # Set up an L3 store against the same tmp DB
    l3_store = L3SummaryStore(db_path=l2_store_with_schema.db_path)
    await l3_store.initialize()

    # Seed two episodes in the window, both active
    await l2_store_with_schema.create_episode(
        episode_id="ep-a", time_start=100.0, time_end=200.0,
    )
    await l2_store_with_schema.update_episode(episode_id="ep-a", status="active")
    await l2_store_with_schema.create_episode(
        episode_id="ep-b", time_start=300.0, time_end=400.0,
    )
    await l2_store_with_schema.update_episode(episode_id="ep-b", status="active")

    stub_output = DiaryNarrativeOutput(
        essence_prose="这是一段周日的样子。",
        narrative_style="diary_2p",
        slices=[
            DiarySliceNarrative(episode_id="ep-a", slice_narrative="下午你读了文档。", slice_sensory_detail="光线柔软。"),
            DiarySliceNarrative(episode_id="ep-b", slice_narrative="深夜还亮着屏。"),
        ],
    )
    client = _StubClient(stub_output)

    orchestrator = DiaryNarrativeOrchestrator(
        l2_store=l2_store_with_schema, l3_store=l3_store, llm_client=client,
    )

    result = await orchestrator.generate_for_window(
        scale="day", period_start=0.0, period_end=500.0, insight_key="diary-2026-05-17",
    )

    assert result.episode_count == 2
    assert result.essence_prose_chars > 0

    # L2 episodes received their narratives
    ep_a = await l2_store_with_schema.get_episode(episode_id="ep-a")
    assert ep_a["slice_narrative"] == "下午你读了文档。"
    assert ep_a["slice_sensory_detail"] == "光线柔软。"
    ep_b = await l2_store_with_schema.get_episode(episode_id="ep-b")
    assert ep_b["slice_narrative"] == "深夜还亮着屏。"
    assert ep_b["slice_sensory_detail"] == ""

    # L3 received the essence prose
    found = await l3_store._find_summary_by_insight_key(insight_key="diary-2026-05-17")
    assert found is not None
    assert found["narrative_style"] == "diary_2p"
    assert found["essence_prose"] == "这是一段周日的样子。"


@pytest.mark.asyncio
async def test_generate_for_window_skips_when_no_episodes(
    l2_store_with_schema: L2CognitionStore,
):
    l3_store = L3SummaryStore(db_path=l2_store_with_schema.db_path)
    await l3_store.initialize()

    client = _StubClient(DiaryNarrativeOutput(essence_prose="", slices=[]))
    orchestrator = DiaryNarrativeOrchestrator(
        l2_store=l2_store_with_schema, l3_store=l3_store, llm_client=client,
    )

    result = await orchestrator.generate_for_window(
        scale="day", period_start=0.0, period_end=500.0, insight_key="diary-empty",
    )

    assert result.episode_count == 0
    assert result.essence_prose_chars == 0
    # LLM was NOT called
    assert client.calls == []
    # No L3 summary was created
    found = await l3_store._find_summary_by_insight_key(insight_key="diary-empty")
    assert found is None


@pytest.mark.asyncio
async def test_generate_for_window_handles_empty_llm_output(
    l2_store_with_schema: L2CognitionStore,
):
    """If the LLM returns empty content (e.g. rate-limited), the orchestrator should be a no-op."""
    l3_store = L3SummaryStore(db_path=l2_store_with_schema.db_path)
    await l3_store.initialize()

    await l2_store_with_schema.create_episode(
        episode_id="ep-x", time_start=100.0, time_end=200.0,
    )
    await l2_store_with_schema.update_episode(episode_id="ep-x", status="active")

    client = _StubClient(DiaryNarrativeOutput())  # all defaults — empty
    orchestrator = DiaryNarrativeOrchestrator(
        l2_store=l2_store_with_schema, l3_store=l3_store, llm_client=client,
    )

    result = await orchestrator.generate_for_window(
        scale="day", period_start=0.0, period_end=500.0, insight_key="diary-empty-llm",
    )

    assert result.essence_prose_chars == 0
    # Episode narrative was NOT written (empty output)
    ep = await l2_store_with_schema.get_episode(episode_id="ep-x")
    assert ep["slice_narrative"] == ""
    # No L3 summary
    found = await l3_store._find_summary_by_insight_key(insight_key="diary-empty-llm")
    assert found is None


@pytest.mark.asyncio
async def test_generate_for_window_forwards_l1_excerpts_to_llm(
    l2_store_with_schema: L2CognitionStore,
):
    """When l1_store is wired, orchestrator should query per-episode and
    pass excerpts under each episode_id to the LLM client."""
    l3_store = L3SummaryStore(db_path=l2_store_with_schema.db_path)
    await l3_store.initialize()

    await l2_store_with_schema.create_episode(
        episode_id="ep-a", time_start=100.0, time_end=200.0,
    )
    await l2_store_with_schema.update_episode(episode_id="ep-a", status="active")
    await l2_store_with_schema.create_episode(
        episode_id="ep-b", time_start=300.0, time_end=400.0,
    )
    await l2_store_with_schema.update_episode(episode_id="ep-b", status="active")

    # Different L1 content per window so we can verify routing.
    l1_store = _StubL1Store(events_by_window={
        (100.0, 200.0): [
            {"content": "Anthropic sleep agency 论文导读", "timestamp": 150.0},
            {"content": "Anthropic sleep agency 论文导读", "timestamp": 160.0},  # dup
        ],
        (300.0, 400.0): [
            {"content": "GitHub Copilot memory 设计文档", "timestamp": 350.0},
        ],
    })

    client = _StubClient(DiaryNarrativeOutput(essence_prose="x", slices=[]))
    orchestrator = DiaryNarrativeOrchestrator(
        l2_store=l2_store_with_schema, l3_store=l3_store, llm_client=client,
        l1_store=l1_store,
    )

    await orchestrator.generate_for_window(
        scale="day", period_start=0.0, period_end=500.0, insight_key="diary-excerpts",
    )

    assert len(client.calls) == 1
    excerpts = client.calls[0]["excerpts_by_episode"]
    assert excerpts["ep-a"] == ["Anthropic sleep agency 论文导读"]
    assert excerpts["ep-b"] == ["GitHub Copilot memory 设计文档"]
    # L1 queried per-episode with the right window
    queried_windows = [(c["start_time"], c["end_time"]) for c in l1_store.calls]
    assert (100.0, 200.0) in queried_windows
    assert (300.0, 400.0) in queried_windows


@pytest.mark.asyncio
async def test_generate_for_window_without_l1_store_sends_empty_excerpts(
    l2_store_with_schema: L2CognitionStore,
):
    """Backward compat: no l1_store → llm_client gets empty excerpts dict, not crash."""
    l3_store = L3SummaryStore(db_path=l2_store_with_schema.db_path)
    await l3_store.initialize()

    await l2_store_with_schema.create_episode(
        episode_id="ep-x", time_start=100.0, time_end=200.0,
    )
    await l2_store_with_schema.update_episode(episode_id="ep-x", status="active")

    client = _StubClient(DiaryNarrativeOutput(essence_prose="x", slices=[]))
    orchestrator = DiaryNarrativeOrchestrator(
        l2_store=l2_store_with_schema, l3_store=l3_store, llm_client=client,
        # l1_store omitted (None)
    )

    await orchestrator.generate_for_window(
        scale="day", period_start=0.0, period_end=500.0, insight_key="diary-no-l1",
    )

    assert len(client.calls) == 1
    assert client.calls[0]["excerpts_by_episode"] == {}
