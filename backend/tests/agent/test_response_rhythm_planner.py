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
        "第一段先接住你的感受：这件事确实会让人有点不踏实，因为你已经投入了不少心力。"
        "先别急着把它判断成失败，我们可以先把眼前最重要的部分理清楚。\n\n"
        "第二段给出核心判断：现在最值得做的是把目标缩小到一个能完成的小动作。"
        "只要这个动作完成了，后面的选择就会更清楚，也不会一直被同一个问题拖住。\n\n"
        "第三段给出下一步：今天先留出一小段安静时间，把要处理的事情写成一句话。"
        "然后只选其中最容易开始的一项做十分钟，先让事情重新动起来。"
    )

    plan = await planner.plan(
        user_message="我现在有点乱，应该怎么开始？",
        response_text=response,
        execution_mode="direct_llm",
        ux_plan={"assistant_surface_mode": "final_only"},
    )

    assert plan is not None
    assert plan.mode == "multi_message"
    assert [segment.content for segment in plan.segments] == [
        "第一段先接住你的感受：这件事确实会让人有点不踏实，因为你已经投入了不少心力。先别急着把它判断成失败，我们可以先把眼前最重要的部分理清楚。",
        "第二段给出核心判断：现在最值得做的是把目标缩小到一个能完成的小动作。只要这个动作完成了，后面的选择就会更清楚，也不会一直被同一个问题拖住。",
        "第三段给出下一步：今天先留出一小段安静时间，把要处理的事情写成一句话。然后只选其中最容易开始的一项做十分钟，先让事情重新动起来。",
    ]
    assert [segment.intent for segment in plan.segments] == ["acknowledge", "answer", "next_step"]
    assert [segment.delay_ms for segment in plan.segments] == [0, 1000, 1000]
    assert prompt_service.calls[0]["json_mode"] is True


@pytest.mark.asyncio
async def test_response_rhythm_planner_preserves_structured_technical_lists(monkeypatch) -> None:
    monkeypatch.setattr(
        rhythm_module,
        "get_user_preference",
        lambda key, default=None: True if key == "conversation_rhythm_enabled" else default,
    )
    prompt_service = _FakePromptService('{"groups": []}')
    planner = ResponseRhythmPlanner(prompt_service=prompt_service)

    response = (
        "这份文档主要说明了 MCP 服务器的几个核心机制。\n\n"
        "1. 条件性工具注册：服务器会根据客户端能力动态注册工具，而不是启动时全部加载。\n\n"
        "2. 资源订阅管理：服务器维护映射表，追踪哪些 Session 订阅了哪些资源 URI。\n\n"
        "3. 会话级资源：工具可以把临时结果注册为资源，供客户端按需读取。\n\n"
        "4. 模拟日志：服务器可以推送不同级别的日志，用来测试客户端处理能力。\n\n"
        "简而言之，它展示了动态能力协商、实时数据推送和调试日志。"
    )

    plan = await planner.plan(
        user_message="这段 MCP 技术文档在讲什么机制？",
        response_text=response,
        execution_mode="direct_llm",
        ux_plan={"assistant_surface_mode": "final_only"},
    )

    assert plan is None
    assert prompt_service.calls == []


@pytest.mark.asyncio
async def test_response_rhythm_planner_rejects_three_groups_for_technical_answer(monkeypatch) -> None:
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
                    {"unit_ids": ["u2"], "intent": "explain", "delay_ms": 1000},
                    {"unit_ids": ["u3"], "intent": "next_step", "delay_ms": 1200},
                ]
            }
        )
    )
    planner = ResponseRhythmPlanner(prompt_service=prompt_service)

    response = (
        "这套 MCP 服务器的核心是能力协商：客户端握手后，服务器根据能力决定哪些工具可以注册。\n\n"
        "资源订阅会按 Session 和 URI 维护映射，所以同一个资源更新时可以只推送给相关客户端。\n\n"
        "如果要继续优化，重点应该放在订阅生命周期和错误日志上，避免断连后留下无效状态。"
    )

    plan = await planner.plan(
        user_message="这个 MCP server 的机制怎么理解？",
        response_text=response,
        execution_mode="direct_llm",
        ux_plan={"assistant_surface_mode": "final_only"},
    )

    assert plan is None
    assert len(prompt_service.calls) == 1
    payload = json.loads(prompt_service.calls[0]["messages"][0]["content"])
    assert payload["content_features"]["technical"] is True
    assert payload["content_features"]["max_groups"] == 2


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
    assert [segment.delay_ms for segment in plan.segments] == [0, 1000]
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
async def test_response_rhythm_planner_rejects_three_groups_for_compact_cjk_answer(monkeypatch) -> None:
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
                    {"unit_ids": ["u2"], "intent": "explain", "delay_ms": 1000},
                    {"unit_ids": ["u3"], "intent": "afterthought", "delay_ms": 1200},
                ]
            }
        )
    )
    planner = ResponseRhythmPlanner(prompt_service=prompt_service)

    plan = await planner.plan(
        user_message="这是周笑话吗？",
        response_text="想多了。这是数学笑话。在二进制世界里，0和1就是全部真理。没有性别，只有电平高低。这个误读比这段代码更吵。",
        execution_mode="direct_llm",
        ux_plan={"assistant_surface_mode": "final_only"},
    )

    assert plan is None


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
