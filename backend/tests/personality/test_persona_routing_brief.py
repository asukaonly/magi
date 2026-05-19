"""Tests for the per-persona ContextDecider routing brief."""

from __future__ import annotations

from magi.personality.loader import (
    PersonalityConfig,
    QuietHour,
    SignatureTrigger,
)
from magi.personality.persona_routing_brief import build_persona_routing_brief


def test_empty_config_returns_empty_string() -> None:
    config = PersonalityConfig()
    assert build_persona_routing_brief(config) == ""


def test_none_config_returns_empty_string() -> None:
    assert build_persona_routing_brief(None) == ""


def test_renders_triggers_and_quiet_hours() -> None:
    config = PersonalityConfig(
        signature_triggers=[
            SignatureTrigger(
                trigger_id="absurdity",
                activates_when="用户整出比她更离谱的活",
                behavior_shift="当场认大哥",
            ),
            SignatureTrigger(
                trigger_id="crisis",
                activates_when="用户面临数据泄露",
                behavior_shift="表演清零",
            ),
        ],
        quiet_hours=[
            QuietHour(condition="用户提出简单事实问题、代码调试、执行任务", clamps={"persona_intensity_max": 1}),
        ],
    )

    brief = build_persona_routing_brief(config)

    assert "## Persona Routing Menu" in brief
    assert "### Available Persona Triggers" in brief
    assert "- absurdity: 用户整出比她更离谱的活" in brief
    assert "- crisis: 用户面临数据泄露" in brief
    assert "### Persona-Defined Quiet Hour Conditions" in brief
    assert "- 用户提出简单事实问题、代码调试、执行任务" in brief
    # behavior_shift / clamps must not leak — they belong to the planner,
    # not the routing classifier.
    assert "当场认大哥" not in brief
    assert "persona_intensity_max" not in brief


def test_skips_triggers_with_missing_id_or_condition() -> None:
    config = PersonalityConfig(
        signature_triggers=[
            SignatureTrigger(trigger_id="", activates_when="empty id"),
            SignatureTrigger(trigger_id="no_cond", activates_when=""),
            SignatureTrigger(trigger_id="ok", activates_when="works"),
        ],
    )

    brief = build_persona_routing_brief(config)

    assert "- ok: works" in brief
    assert "empty id" not in brief
    assert "no_cond" not in brief


def test_triggers_only_renders_just_triggers_section() -> None:
    config = PersonalityConfig(
        signature_triggers=[
            SignatureTrigger(trigger_id="absurdity", activates_when="离谱"),
        ],
    )

    brief = build_persona_routing_brief(config)

    assert "### Available Persona Triggers" in brief
    assert "### Persona-Defined Quiet Hour Conditions" not in brief
