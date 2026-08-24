from __future__ import annotations

from types import SimpleNamespace

import pytest

from magi.agent import response_rhythm as rhythm_module
from magi.agent.response_rhythm import (
    ResponseRhythmPlanner,
    _CEIL_MS,
    _FLOOR_MS,
    _compute_delay_ms,
)


def _enable_rhythm(monkeypatch, *, on: bool = True) -> None:
    def fake_get_user_preference(key, default=None):  # type: ignore[no-untyped-def]
        if key == "conversation_rhythm_enabled":
            return on
        if key == "conversation_rhythm_mode":
            return "natural" if on else "off"
        return default

    monkeypatch.setattr(rhythm_module, "get_user_preference", fake_get_user_preference)


def test_split_on_sentinel_basic() -> None:
    split_on_sentinel = rhythm_module.split_on_sentinel

    assert split_on_sentinel("a‖b‖c") == ["a", "b", "c"]
    assert split_on_sentinel("  a ‖  b  ") == ["a", "b"]
    assert split_on_sentinel("a‖‖b") == ["a", "b"]
    assert split_on_sentinel("solo") == ["solo"]
    assert split_on_sentinel("‖a‖") == ["a"]


def test_strip_segmentation_sentinel_removes_plain_residue() -> None:
    strip_segmentation_sentinel = rhythm_module.strip_segmentation_sentinel

    assert strip_segmentation_sentinel("a‖b‖c") == "a b c"
    assert strip_segmentation_sentinel("no marks") == "no marks"
    assert "‖" not in strip_segmentation_sentinel("x‖y")


def test_strip_segmentation_sentinel_preserves_protected_layout() -> None:
    strip_segmentation_sentinel = rhythm_module.strip_segmentation_sentinel
    text = "推荐这几个：‖- 选项一‖- 选项二‖- 选项三"

    assert strip_segmentation_sentinel(text) == (
        "推荐这几个：\n- 选项一\n- 选项二\n- 选项三"
    )


@pytest.mark.asyncio
async def test_response_rhythm_planner_splits_on_sentinel(monkeypatch) -> None:
    _enable_rhythm(monkeypatch)
    planner = ResponseRhythmPlanner()

    plan = await planner.plan(
        response_text="看番？行啊。‖不过现在的番剧不少。‖你最近在看哪部？",
        persona=None,
    )

    assert plan is not None
    assert plan.mode == "multi_message"
    assert plan.aggregate_text == "看番？行啊。\n不过现在的番剧不少。\n你最近在看哪部？"
    assert [segment.content for segment in plan.segments] == [
        "看番？行啊。",
        "不过现在的番剧不少。",
        "你最近在看哪部？",
    ]
    assert [segment.segment_index for segment in plan.segments] == [0, 1, 2]
    assert plan.segments[0].delay_ms == 0
    assert all(_FLOOR_MS <= segment.delay_ms <= _CEIL_MS for segment in plan.segments[1:])


@pytest.mark.asyncio
async def test_response_rhythm_planner_allows_six_persona_segments(monkeypatch) -> None:
    _enable_rhythm(monkeypatch)
    planner = ResponseRhythmPlanner()

    plan = await planner.plan(response_text="一‖二‖三‖四‖五‖六", persona=None)

    assert plan is not None
    assert len(plan.segments) == 6


@pytest.mark.asyncio
async def test_response_rhythm_planner_rejects_more_than_six_segments(monkeypatch) -> None:
    _enable_rhythm(monkeypatch)
    planner = ResponseRhythmPlanner()

    plan = await planner.plan(response_text="一‖二‖三‖四‖五‖六‖七", persona=None)

    assert plan is None


@pytest.mark.asyncio
async def test_response_rhythm_planner_falls_back_for_protected_structure(monkeypatch) -> None:
    _enable_rhythm(monkeypatch)
    planner = ResponseRhythmPlanner()

    text = "推荐这几个：‖- 选项一‖- 选项二‖- 选项三"
    plan = await planner.plan(response_text=text, persona=None)

    assert plan is None


@pytest.mark.asyncio
async def test_response_rhythm_planner_mode_off_disables_planning(monkeypatch) -> None:
    _enable_rhythm(monkeypatch, on=False)
    planner = ResponseRhythmPlanner()

    plan = await planner.plan(response_text="第一段‖第二段", persona=None)

    assert plan is None


@pytest.mark.asyncio
async def test_response_rhythm_planner_skips_streamed_turns(monkeypatch) -> None:
    _enable_rhythm(monkeypatch)
    planner = ResponseRhythmPlanner()

    plan = await planner.plan(response_text="第一段‖第二段", persona=None, streamed=True)

    assert plan is None


@pytest.mark.asyncio
@pytest.mark.parametrize("surface_mode", ["none", "reaction_only"])
async def test_response_rhythm_planner_skips_non_visible_surfaces(monkeypatch, surface_mode) -> None:
    _enable_rhythm(monkeypatch)
    planner = ResponseRhythmPlanner()

    plan = await planner.plan(
        response_text="第一段‖第二段",
        persona=None,
        ux_plan={"assistant_surface_mode": surface_mode},
    )

    assert plan is None


def test_extract_persona_rhythm_from_prompt_context() -> None:
    from magi.agent.response_rhythm import extract_persona_rhythm

    plan = SimpleNamespace(
        register="chat",
        persona_intensity=2,
        idiolect={"sentence_style": "爱用短句"},
    )
    ctx = SimpleNamespace(self_memory=SimpleNamespace(persona_turn_plan=plan))

    signal = extract_persona_rhythm(ctx)
    assert signal is not None
    assert signal.register == "chat"
    assert signal.persona_intensity == 2
    assert signal.sentence_style == "爱用短句"

    assert extract_persona_rhythm(SimpleNamespace()) is None
    assert extract_persona_rhythm(SimpleNamespace(self_memory=SimpleNamespace(persona_turn_plan=None))) is None

    crisis_plan = SimpleNamespace(register="crisis", persona_intensity=0, idiolect={})
    crisis_ctx = SimpleNamespace(self_memory=SimpleNamespace(persona_turn_plan=crisis_plan))
    crisis_signal = extract_persona_rhythm(crisis_ctx)
    assert crisis_signal is not None
    assert crisis_signal.persona_intensity == 0
    assert crisis_signal.register == "crisis"
    assert crisis_signal.sentence_style == ""

    chat_plan = SimpleNamespace(
        register="chat", persona_intensity=2, idiolect={"sentence_style": "x", "chattiness": 0.8}
    )
    chat_ctx = SimpleNamespace(self_memory=SimpleNamespace(persona_turn_plan=chat_plan))
    chat_signal = extract_persona_rhythm(chat_ctx)
    assert chat_signal.chattiness == 0.8

    miss = extract_persona_rhythm(
        SimpleNamespace(self_memory=SimpleNamespace(persona_turn_plan=SimpleNamespace(
            register="chat", persona_intensity=1, idiolect={"sentence_style": ""})))
    )
    assert miss.chattiness == 0.5
    clamped = extract_persona_rhythm(
        SimpleNamespace(self_memory=SimpleNamespace(persona_turn_plan=SimpleNamespace(
            register="chat", persona_intensity=1, idiolect={"chattiness": 9.0})))
    )
    assert clamped.chattiness == 1.0


@pytest.mark.asyncio
async def test_postprocess_forwards_persona_and_raw_response_to_rhythm_planner() -> None:
    from magi.agent.task_agents.common import (
        ExecutionMode,
        ExecutionResult,
        RhythmPersonaSignal,
    )
    from magi.chat.task_agent.postprocess_service import ChatPostProcessService

    received: dict = {}

    class _RecordingPlanner:
        async def plan(self, **kwargs):  # type: ignore[no-untyped-def]
            received.update(kwargs)
            return None

    from magi.chat.task_agent.postprocess.utils import normalize_mode
    service = object.__new__(ChatPostProcessService)
    service._response_rhythm_planner = _RecordingPlanner()
    service._normalize_mode = normalize_mode

    signal = RhythmPersonaSignal(register="chat", persona_intensity=2, sentence_style="爱用短句")
    result = ExecutionResult(
        mode=None,
        response_text="alpha‖beta",
        root_user_message="hi",
        persona_rhythm=signal,
    )

    await service._build_response_rhythm_plan(
        context=SimpleNamespace(latest_user_message="hi"),
        result=result,
        response_text="alpha‖beta",
        ux_plan={},
    )
    assert received.get("persona") is signal
    assert received.get("response_text") == "alpha‖beta"
    assert "user_message" not in received
    assert "execution_mode" not in received


def test_rhythm_level_multiplies_scene_and_chattiness() -> None:
    from magi.agent.task_agents.common import RhythmPersonaSignal
    from magi.agent.response_rhythm import _rhythm_level

    assert abs(_rhythm_level(None) - 0.25) < 1e-9
    crisis = RhythmPersonaSignal(register="crisis", persona_intensity=0, chattiness=0.9)
    assert _rhythm_level(crisis) == 0.0
    chatty = RhythmPersonaSignal(register="chat", persona_intensity=2, chattiness=0.75)
    assert abs(_rhythm_level(chatty) - 0.75) < 1e-9
    reserved = RhythmPersonaSignal(register="chat", persona_intensity=2, chattiness=0.30)
    assert abs(_rhythm_level(reserved) - 0.30) < 1e-9


def test_rhythm_profile_maps_level_to_speed_and_max_segments() -> None:
    from magi.agent.response_rhythm import _rhythm_profile

    bias_lo, speed_lo, max_lo = _rhythm_profile(0.1)
    assert "exactly one group" in bias_lo and max_lo == 1 and speed_lo > 1.0
    _bias_mid, speed_mid, max_mid = _rhythm_profile(0.6)
    assert max_mid == 3 and speed_mid < 1.0
    _bias_hi, speed_hi, max_hi = _rhythm_profile(0.9)
    assert max_hi == 6 and speed_hi < speed_mid
    assert _rhythm_profile(0.20)[2] == 2
    assert _rhythm_profile(0.50)[2] == 3
    assert _rhythm_profile(0.75)[2] == 6


def test_compute_delay_ms_scales_with_length_and_clamps() -> None:
    class _FixedRng:
        @staticmethod
        def uniform(_a: float, _b: float) -> float:
            return 1.0

    rng = _FixedRng()
    assert _FLOOR_MS == 1000
    assert _compute_delay_ms("嗯", rng=rng) == _FLOOR_MS
    mid = _compute_delay_ms("字" * 30, rng=rng)
    assert mid == 1500
    assert _compute_delay_ms("字" * 1000, rng=rng) == _CEIL_MS
    assert _compute_delay_ms("a" * 100, rng=rng) < _compute_delay_ms("字" * 100, rng=rng)
    slow = _compute_delay_ms("字" * 30, speed_factor=1.3, rng=rng)
    fast = _compute_delay_ms("字" * 30, speed_factor=0.8, rng=rng)
    assert fast < mid < slow
