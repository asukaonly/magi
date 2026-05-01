from __future__ import annotations

import json

import pytest

from magi.agent.task_agents.chat import rhythm as rhythm_module
from magi.agent.task_agents.chat.rhythm import ResponseRhythmPlanner


class _FakePromptService:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict] = []

    async def call_llm(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        return self.response


@pytest.mark.asyncio
async def test_response_rhythm_planner_groups_existing_units(monkeypatch) -> None:
    monkeypatch.setattr(
        rhythm_module,
        "get_user_preference",
        lambda key, default=None: True if key == "conversation_rhythm_enabled" else default,
    )
    prompt_service = _FakePromptService(
        json.dumps(
            {
                "groups": [
                    {"unit_ids": ["u1"], "intent": "acknowledge", "delay_ms": 0},
                    {"unit_ids": ["u2"], "intent": "answer", "delay_ms": 600},
                    {"unit_ids": ["u3"], "intent": "next_step", "delay_ms": 900},
                ]
            }
        )
    )
    planner = ResponseRhythmPlanner(prompt_service=prompt_service)

    response = (
        "第一段确认问题并给出方向，说明这个能力应该被看成展示层节奏，而不是第二个回答模型。"
        "它保留主模型的原始判断和语气，只负责让用户先看到一个自然的进入点。\n\n"
        "第二段说明核心答案和约束：主模型仍然产出唯一可信的完整回答，节奏规划器只能引用原文单元。"
        "如果规划结果缺段、乱序或者引用不存在的单元，就直接降级为单条回复。\n\n"
        "第三段给出下一步做法：先做内部 JSON 规划和多消息展示，暂时不做 segment 内流式输出。"
        "等这个路径稳定后，再考虑更细的延迟调度和用户可见设置。"
    )

    plan = await planner.plan(
        user_message="我们怎么做节奏回复？",
        response_text=response,
        execution_mode="direct_llm",
        ux_plan={"assistant_surface_mode": "final_only"},
    )

    assert plan is not None
    assert plan.mode == "multi_message"
    assert [segment.content for segment in plan.segments] == [
        "第一段确认问题并给出方向，说明这个能力应该被看成展示层节奏，而不是第二个回答模型。它保留主模型的原始判断和语气，只负责让用户先看到一个自然的进入点。",
        "第二段说明核心答案和约束：主模型仍然产出唯一可信的完整回答，节奏规划器只能引用原文单元。如果规划结果缺段、乱序或者引用不存在的单元，就直接降级为单条回复。",
        "第三段给出下一步做法：先做内部 JSON 规划和多消息展示，暂时不做 segment 内流式输出。等这个路径稳定后，再考虑更细的延迟调度和用户可见设置。",
    ]
    assert [segment.intent for segment in plan.segments] == ["acknowledge", "answer", "next_step"]
    assert prompt_service.calls[0]["json_mode"] is True


@pytest.mark.asyncio
async def test_response_rhythm_planner_splits_short_cjk_sentence_units(monkeypatch) -> None:
    monkeypatch.setattr(
        rhythm_module,
        "get_user_preference",
        lambda key, default=None: True if key == "conversation_rhythm_enabled" else default,
    )
    prompt_service = _FakePromptService(
        json.dumps(
            {
                "groups": [
                    {"unit_ids": ["u1"], "intent": "answer", "delay_ms": 0},
                    {"unit_ids": ["u2", "u3"], "intent": "explain", "delay_ms": 500},
                ]
            }
        )
    )
    planner = ResponseRhythmPlanner(prompt_service=prompt_service)

    response = (
        "先别把节奏规划当成第二个回答模型。"
        "主模型正常说完，保留原来的判断。"
        "然后只把自然断句拆成两三条气泡，让它像聊天而不是报告。"
    )

    plan = await planner.plan(
        user_message="这个怎么触发？",
        response_text=response,
        execution_mode="direct_llm",
        ux_plan={"assistant_surface_mode": "final_only"},
    )

    assert plan is not None
    assert [segment.content for segment in plan.segments] == [
        "先别把节奏规划当成第二个回答模型。",
        "主模型正常说完，保留原来的判断。\n然后只把自然断句拆成两三条气泡，让它像聊天而不是报告。",
    ]
    payload = json.loads(prompt_service.calls[0]["messages"][0]["content"])
    assert [unit["text"] for unit in payload["units"]] == [
        "先别把节奏规划当成第二个回答模型。",
        "主模型正常说完，保留原来的判断。",
        "然后只把自然断句拆成两三条气泡，让它像聊天而不是报告。",
    ]


@pytest.mark.asyncio
async def test_response_rhythm_planner_keeps_short_latin_reply_single_message(monkeypatch) -> None:
    monkeypatch.setattr(
        rhythm_module,
        "get_user_preference",
        lambda key, default=None: True if key == "conversation_rhythm_enabled" else default,
    )
    prompt_service = _FakePromptService('{"groups": []}')
    planner = ResponseRhythmPlanner(prompt_service=prompt_service)

    plan = await planner.plan(
        user_message="How does it trigger?",
        response_text="It triggers only when the answer has multiple useful units. Short replies stay as one bubble.",
        execution_mode="direct_llm",
        ux_plan={"assistant_surface_mode": "final_only"},
    )

    assert plan is None
    assert prompt_service.calls == []


@pytest.mark.asyncio
async def test_response_rhythm_planner_mode_off_disables_planning(monkeypatch) -> None:
    def fake_get_user_preference(key, default=None):  # type: ignore[no-untyped-def]
        if key == "conversation_rhythm_enabled":
            return True
        if key == "conversation_rhythm_mode":
            return "off"
        return default

    monkeypatch.setattr(rhythm_module, "get_user_preference", fake_get_user_preference)
    prompt_service = _FakePromptService('{"groups": []}')
    planner = ResponseRhythmPlanner(prompt_service=prompt_service)

    plan = await planner.plan(
        user_message="拆一下",
        response_text=(
            "第一段足够长，用来确认关闭模式会跳过规划。"
            "第二段也足够长，用来确认即使 enabled 字段为真，mode=off 仍然优先。"
        ),
        execution_mode="direct_llm",
        ux_plan={"assistant_surface_mode": "final_only"},
    )

    assert plan is None
    assert prompt_service.calls == []


@pytest.mark.asyncio
async def test_response_rhythm_planner_rejects_content_drift(monkeypatch) -> None:
    monkeypatch.setattr(
        rhythm_module,
        "get_user_preference",
        lambda key, default=None: True if key == "conversation_rhythm_enabled" else default,
    )
    prompt_service = _FakePromptService(
        json.dumps(
            {
                "groups": [
                    {"unit_ids": ["u1"], "intent": "answer", "delay_ms": 0},
                    {"unit_ids": ["u3"], "intent": "answer", "delay_ms": 500},
                ]
            }
        )
    )
    planner = ResponseRhythmPlanner(prompt_service=prompt_service)

    plan = await planner.plan(
        user_message="拆一下",
        response_text=(
            "第一段足够长，用来说明原始回答中的第一块内容应该完整保留，不能被规划模型改写。"
            "这段文本只是测试单元，不代表真实用户可见内容。\n\n"
            "第二段也足够长，用来说明规划模型如果引用不存在的单元，就必须被后端校验拒绝。"
            "这样可以防止模型漂移或者凭空创造新的展示内容。"
        ),
        execution_mode="direct_llm",
        ux_plan={"assistant_surface_mode": "final_only"},
    )

    assert plan is None


@pytest.mark.asyncio
async def test_response_rhythm_planner_skips_streamed_turns(monkeypatch) -> None:
    monkeypatch.setattr(
        rhythm_module,
        "get_user_preference",
        lambda key, default=None: True if key == "conversation_rhythm_enabled" else default,
    )
    prompt_service = _FakePromptService('{"groups": []}')
    planner = ResponseRhythmPlanner(prompt_service=prompt_service)

    plan = await planner.plan(
        user_message="拆一下",
        response_text=(
            "第一段足够长，用来确认 streamed turn 不会进入节奏规划。"
            "这可以避免 JSON 规划内容和用户可见 token stream 混在一起。\n\n"
            "第二段足够长，用来确认即使偏好开启，只要本轮已经流式输出，也会保留原来的单气泡路径。"
            "这个限制让首版行为更稳。"
        ),
        execution_mode="direct_llm",
        ux_plan={"assistant_surface_mode": "final_only"},
        streamed=True,
    )

    assert plan is None
    assert prompt_service.calls == []
