"""Tests for DiaryNarrativeLLMClient (LLM call stubbed via monkeypatch)."""

from __future__ import annotations

import json

import pytest


class _StubResponse:
    def __init__(self, content: str) -> None:
        self.content = content
        self.usage = None


class _StubAdapter:
    provider_name = "stub"
    model_name = "stub-model"


class _StubPool:
    """Minimal stand-in for ScenarioLLMPool with .get() and .get_selection()."""

    def __init__(self) -> None:
        self._adapter = _StubAdapter()

    def get(self, scenario):
        return self._adapter

    def get_selection(self, scenario):
        return None


@pytest.mark.asyncio
async def test_generate_returns_parsed_output(monkeypatch):
    """The client should hand a JSON-mode chat call to the provider bridge,
    parse the response, and return a DiaryNarrativeOutput."""
    from magi.timeline.narrative.llm_client import DiaryNarrativeLLMClient
    from magi.llm import LLMProviderBridge

    payload = {
        "essence_prose": "周日的样子。",
        "narrative_style": "diary_2p",
        "slices": [{"episode_id": "ep-1", "slice_narrative": "你读了文档。"}],
    }
    calls: list[dict] = []

    async def fake_chat_response(self, **kwargs):
        calls.append(kwargs)
        return _StubResponse(json.dumps(payload))

    monkeypatch.setattr(LLMProviderBridge, "chat_response", fake_chat_response)

    pool = _StubPool()
    client = DiaryNarrativeLLMClient(scenario_llm_pool=pool)
    out = await client.generate(
        scale="day", period_start=0.0, period_end=86400.0,
        episodes=[{"episode_id": "ep-1", "time_start": 100.0, "time_end": 200.0, "label": "x"}],
        place_hints=[],
    )

    assert out.essence_prose == "周日的样子。"
    assert out.narrative_style == "diary_2p"
    assert len(out.slices) == 1
    assert out.slices[0].episode_id == "ep-1"
    # The pool was called once with json_mode=True
    assert len(calls) == 1
    assert calls[0].get("json_mode") is True


@pytest.mark.asyncio
async def test_generate_returns_empty_on_no_adapter():
    """If the scenario pool has no adapter, the mixin returns {} and the client
    surfaces an empty DiaryNarrativeOutput (no crash)."""
    from magi.timeline.narrative.llm_client import DiaryNarrativeLLMClient
    from magi.timeline.narrative.output_schema import DiaryNarrativeOutput

    class _NoPool:
        def get(self, scenario):
            return None

        def get_selection(self, scenario):
            return None

    client = DiaryNarrativeLLMClient(scenario_llm_pool=_NoPool())
    out = await client.generate(
        scale="day", period_start=0.0, period_end=1.0, episodes=[], place_hints=[],
    )
    assert isinstance(out, DiaryNarrativeOutput)
    assert out.essence_prose == ""
    assert out.slices == []


@pytest.mark.asyncio
async def test_generate_forwards_excerpts_into_prompt(monkeypatch):
    """The client should pass excerpts_by_episode through to the prompt builder
    so the prompt text the provider sees actually contains the snippets."""
    from magi.timeline.narrative.llm_client import DiaryNarrativeLLMClient
    from magi.llm import LLMProviderBridge

    captured_prompts: list[str] = []

    async def fake_chat_response(self, **kwargs):
        # The user prompt is the second message in the messages list
        messages = kwargs.get("messages") or []
        for msg in messages:
            if msg.get("role") == "user":
                captured_prompts.append(msg.get("content", ""))
        return _StubResponse('{"essence_prose": "x", "slices": []}')

    monkeypatch.setattr(LLMProviderBridge, "chat_response", fake_chat_response)

    client = DiaryNarrativeLLMClient(scenario_llm_pool=_StubPool())
    await client.generate(
        scale="day", period_start=0.0, period_end=86400.0,
        episodes=[{"episode_id": "ep-1", "time_start": 100.0, "time_end": 200.0, "label": "x"}],
        place_hints=[],
        excerpts_by_episode={"ep-1": ["sleep agency 论文导读"]},
    )

    assert len(captured_prompts) == 1
    assert "sleep agency 论文导读" in captured_prompts[0]
    assert "事件证据" in captured_prompts[0]


@pytest.mark.asyncio
async def test_generate_rewrites_short_ids_and_remaps_back(monkeypatch):
    """End-to-end short-id contract:
       - the prompt shown to the LLM uses short tags (e1, e2…), not raw UUIDs;
       - the LLM responds with short ids; the client rehydrates them to the
         original full episode_ids before returning."""
    from magi.timeline.narrative.llm_client import DiaryNarrativeLLMClient
    from magi.llm import LLMProviderBridge

    captured_prompts: list[str] = []

    async def fake_chat_response(self, **kwargs):
        messages = kwargs.get("messages") or []
        for msg in messages:
            if msg.get("role") == "user":
                captured_prompts.append(msg.get("content", ""))
        payload = {
            "essence_prose": "essence",
            "slices": [
                {"episode_id": "e1", "slice_narrative": "first"},
                {"episode_id": "e2", "slice_narrative": "second"},
            ],
        }
        return _StubResponse(json.dumps(payload))

    monkeypatch.setattr(LLMProviderBridge, "chat_response", fake_chat_response)

    client = DiaryNarrativeLLMClient(scenario_llm_pool=_StubPool())
    out = await client.generate(
        scale="day", period_start=0.0, period_end=86400.0,
        episodes=[
            {"episode_id": "01KS1M8ZYD4YVNN706VDF9PKC4", "time_start": 100.0, "time_end": 200.0, "label": "a"},
            {"episode_id": "542a7e1b-f0ce-40df-b6ec-a6a5d11f5655", "time_start": 300.0, "time_end": 400.0, "label": "b"},
        ],
        place_hints=[],
        # Excerpts keyed by full id; client should remap to short ids
        excerpts_by_episode={"01KS1M8ZYD4YVNN706VDF9PKC4": ["sleep agency"]},
    )

    # Prompt contained short ids, not raw UUIDs
    assert "e1" in captured_prompts[0]
    assert "e2" in captured_prompts[0]
    assert "01KS1M8ZYD4YVNN706VDF9PKC4" not in captured_prompts[0]
    # Excerpts followed the relabel
    assert "sleep agency" in captured_prompts[0]

    # Output slice ids are remapped back to full ids
    assert out.slices[0].episode_id == "01KS1M8ZYD4YVNN706VDF9PKC4"
    assert out.slices[1].episode_id == "542a7e1b-f0ce-40df-b6ec-a6a5d11f5655"


@pytest.mark.asyncio
async def test_generate_leaves_hallucinated_ids_for_orchestrator_to_skip(monkeypatch):
    """If the LLM ignores the contract and returns a UUID, the client leaves
    it intact so the orchestrator's existing 'unknown episode_id' guard
    skips it (instead of silently mapping to the wrong real episode)."""
    from magi.timeline.narrative.llm_client import DiaryNarrativeLLMClient
    from magi.llm import LLMProviderBridge

    async def fake_chat_response(self, **kwargs):
        payload = {
            "essence_prose": "essence",
            "slices": [
                {"episode_id": "e1", "slice_narrative": "good"},
                {"episode_id": "hallucinated-uuid-xyz", "slice_narrative": "bad"},
            ],
        }
        return _StubResponse(json.dumps(payload))

    monkeypatch.setattr(LLMProviderBridge, "chat_response", fake_chat_response)

    client = DiaryNarrativeLLMClient(scenario_llm_pool=_StubPool())
    out = await client.generate(
        scale="day", period_start=0.0, period_end=86400.0,
        episodes=[{"episode_id": "real-uuid-1", "time_start": 0.0, "time_end": 1.0, "label": "x"}],
        place_hints=[],
    )

    # e1 was remapped; the hallucinated id stays untranslated.
    ids = [s.episode_id for s in out.slices]
    assert ids == ["real-uuid-1", "hallucinated-uuid-xyz"]
