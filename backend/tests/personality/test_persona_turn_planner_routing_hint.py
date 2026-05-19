"""Tests for PersonaTurnPlanner consuming PersonaRoutingHint from the unified router."""

from __future__ import annotations

from magi.personality.loader import (
    PersonalityConfig,
    QuietHour,
    Register,
    SignatureTrigger,
)
from magi.personality.turn_planner import (
    ActivePersonaTrigger,
    PersonaRoutingHint,
    PersonaTurnPlanner,
)


def _seven_like_config() -> PersonalityConfig:
    return PersonalityConfig(
        name="七号",
        registers={
            "chat": Register(description="chat", behavior="chat behavior"),
            "task": Register(description="task", behavior="task behavior"),
            "analysis": Register(description="analysis", behavior="analysis behavior"),
            "emotional": Register(description="emotional", behavior="emotional behavior"),
            "crisis": Register(description="crisis", behavior="crisis behavior"),
        },
        signature_triggers=[
            SignatureTrigger(
                trigger_id="absurdity",
                activates_when="用户整出比她更离谱的活",
                behavior_shift="当场认大哥",
            ),
            SignatureTrigger(
                trigger_id="hostility",
                activates_when="用户用宏大叙事压她",
                behavior_shift="拆逻辑漏洞",
            ),
            SignatureTrigger(
                trigger_id="crisis",
                activates_when="用户面临数据泄露",
                behavior_shift="清零表演",
            ),
        ],
        quiet_hours=[
            QuietHour(
                condition="用户需要认真支持、情绪低落、疲惫、焦虑或安全隐私帮助时",
                clamps={"persona_intensity_max": 1, "sarcasm": "none_to_light"},
            ),
        ],
    )


def test_routing_hint_register_overrides_keyword_choice() -> None:
    config = _seven_like_config()
    planner = PersonaTurnPlanner()

    # User message looks mundane, but the LLM router says emotional.
    plan = planner.build_plan(
        config=config,
        user_message="晚饭吃什么",
        scenario="chat",
        task_category="chat",
        routing_hint=PersonaRoutingHint(register="emotional"),
    )

    assert plan.register == "emotional"
    assert any(qh["condition"] == "emotional_support" for qh in plan.quiet_hours)


def test_routing_hint_resolves_active_triggers_from_config_by_id() -> None:
    config = _seven_like_config()
    planner = PersonaTurnPlanner()

    plan = planner.build_plan(
        config=config,
        user_message="随便聊",
        scenario="chat",
        task_category="chat",
        routing_hint=PersonaRoutingHint(
            register="casual",
            active_trigger_ids=("absurdity",),
            situation_strength="strong",
        ),
    )

    assert [t.trigger_id for t in plan.active_triggers] == ["absurdity"]
    assert plan.active_triggers[0].behavior_shift == "当场认大哥"
    assert plan.active_triggers[0].reason == "routing_hint"
    assert plan.situation_strength == "strong"


def test_routing_hint_silently_drops_unknown_trigger_ids() -> None:
    config = _seven_like_config()
    planner = PersonaTurnPlanner()

    plan = planner.build_plan(
        config=config,
        user_message="随便聊",
        scenario="chat",
        task_category="chat",
        routing_hint=PersonaRoutingHint(
            active_trigger_ids=("tech_curious_hallucinated", "absurdity"),
        ),
    )

    assert [t.trigger_id for t in plan.active_triggers] == ["absurdity"]


def test_routing_hint_caps_active_triggers_at_two() -> None:
    config = _seven_like_config()
    planner = PersonaTurnPlanner()

    plan = planner.build_plan(
        config=config,
        user_message="x",
        scenario="chat",
        task_category="chat",
        routing_hint=PersonaRoutingHint(
            active_trigger_ids=("absurdity", "hostility", "crisis"),
        ),
    )

    assert len(plan.active_triggers) == 2


def test_routing_hint_quiet_hour_matches_config_by_exact_string() -> None:
    config = _seven_like_config()
    planner = PersonaTurnPlanner()

    plan = planner.build_plan(
        config=config,
        user_message="随便聊",
        scenario="chat",
        task_category="chat",
        routing_hint=PersonaRoutingHint(
            register="casual",
            quiet_hour_hints=("用户需要认真支持、情绪低落、疲惫、焦虑或安全隐私帮助时",),
        ),
    )

    conditions = [qh["condition"] for qh in plan.quiet_hours]
    assert "用户需要认真支持、情绪低落、疲惫、焦虑或安全隐私帮助时" in conditions


def test_routing_hint_quiet_hour_ignores_unknown_hints() -> None:
    config = _seven_like_config()
    planner = PersonaTurnPlanner()

    plan = planner.build_plan(
        config=config,
        user_message="random",
        scenario="chat",
        task_category="chat",
        routing_hint=PersonaRoutingHint(
            quiet_hour_hints=("not_in_config",),
        ),
    )

    conditions = [qh["condition"] for qh in plan.quiet_hours]
    # Only the built-in register-derived clamps should fire; the unknown
    # persona-defined hint should be ignored.
    assert "not_in_config" not in conditions


def test_no_routing_hint_falls_back_to_keyword_path() -> None:
    config = _seven_like_config()
    planner = PersonaTurnPlanner()

    # Mundane chat — keyword path returns casual with no active triggers.
    mundane = planner.build_plan(
        config=config,
        user_message="今天晚饭吃什么",
        scenario="chat",
        task_category="chat",
    )
    assert mundane.register in {"casual", "chat"}
    assert mundane.active_triggers == []

    # Crisis keywords — keyword path returns crisis.
    crisis = planner.build_plan(
        config=config,
        user_message="紧急，密码被盗",
        scenario="chat",
        task_category="chat",
    )
    assert crisis.register == "crisis"


def test_routing_hint_register_chat_resolves_to_persona_register_name() -> None:
    # Persona presets that only define "casual" should accept the LLM's "chat"
    # alias, and vice versa.
    config = PersonalityConfig(
        name="alt_persona",
        registers={"chat": Register(description="chat", behavior="b")},
    )
    plan = PersonaTurnPlanner().build_plan(
        config=config,
        user_message="hi",
        scenario="chat",
        task_category="chat",
        routing_hint=PersonaRoutingHint(register="casual"),
    )
    assert plan.register == "chat"


def test_routing_hint_crisis_zeros_persona_intensity() -> None:
    config = _seven_like_config()
    plan = PersonaTurnPlanner().build_plan(
        config=config,
        user_message="anything",
        scenario="chat",
        task_category="chat",
        routing_hint=PersonaRoutingHint(register="crisis", situation_strength="crisis"),
    )
    assert plan.register == "crisis"
    assert plan.persona_intensity == 0
    assert plan.situation_strength == "crisis"


def test_routing_hint_suppresses_play_during_tool_execution() -> None:
    """Tool execution must suppress non-safety triggers even when the LLM
    suggested one. The Persona Layer Architecture mandates this clamp."""
    config = _seven_like_config()
    plan = PersonaTurnPlanner().build_plan(
        config=config,
        user_message="改代码",
        scenario="task",
        task_category="code",
        tools=["edit_file"],
        routing_hint=PersonaRoutingHint(
            register="task",
            active_trigger_ids=("absurdity",),
        ),
    )
    assert plan.register == "task"
    assert [t.trigger_id for t in plan.active_triggers] == []


def test_returned_active_triggers_are_typed() -> None:
    config = _seven_like_config()
    plan = PersonaTurnPlanner().build_plan(
        config=config,
        user_message="x",
        scenario="chat",
        task_category="chat",
        routing_hint=PersonaRoutingHint(active_trigger_ids=("absurdity",)),
    )
    assert all(isinstance(t, ActivePersonaTrigger) for t in plan.active_triggers)
