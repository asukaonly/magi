"""P3.1: cross-turn trigger carryover.

The persona should not snap from "still angry" to "neutral" between
adjacent turns just because the next user message did not re-trigger
the same signature. Carryover applies for exactly one hop with
reduced intensity; chaining is bounded because only NEW (non-carryover)
trigger_ids are written back into ``recent_active_trigger_ids``.
"""

from __future__ import annotations

from magi.personality.loader import (
    PersonalityConfig,
    Register,
    SignatureTrigger,
)
from magi.personality.turn_planner import (
    ActivePersonaTrigger,
    PersonaRoutingHint,
    PersonaTurnPlanner,
)


def _config_with_triggers() -> PersonalityConfig:
    return PersonalityConfig(
        name="七号",
        registers={
            "chat": Register(description="chat", behavior="chat"),
            "task": Register(description="task", behavior="task"),
        },
        signature_triggers=[
            SignatureTrigger(
                trigger_id="absurdity",
                activates_when="user did something absurd",
                behavior_shift="match the absurdity",
                intensity_levels={"low": "quiet", "mid": "normal", "high": "loud"},
            ),
            SignatureTrigger(
                trigger_id="hostility",
                activates_when="user is pressing with grand narratives",
                behavior_shift="dismantle the logic",
                intensity_levels={"mid": "normal"},
            ),
        ],
    )


def test_carryover_fires_when_no_new_trigger() -> None:
    config = _config_with_triggers()
    plan = PersonaTurnPlanner().build_plan(
        config=config,
        user_message="晚饭吃啥",  # no trigger match
        scenario="chat",
        task_category="chat",
        previous_trigger_ids=["absurdity"],
    )

    assert [t.trigger_id for t in plan.active_triggers] == ["absurdity"]
    carryover = plan.active_triggers[0]
    assert carryover.reason == "carryover"


def test_carryover_intensity_is_downgraded() -> None:
    config = _config_with_triggers()
    plan = PersonaTurnPlanner().build_plan(
        config=config,
        user_message="晚饭吃啥",
        scenario="chat",
        task_category="chat",
        previous_trigger_ids=["absurdity"],
    )

    # absurdity intensity_levels has "low", "mid", "high"; downgrade picks "low".
    assert plan.active_triggers[0].intensity == "low"


def test_new_trigger_replaces_carryover() -> None:
    """LLM-supplied new trigger this turn must replace carryover."""
    config = _config_with_triggers()
    plan = PersonaTurnPlanner().build_plan(
        config=config,
        user_message="anything",
        scenario="chat",
        task_category="chat",
        routing_hint=PersonaRoutingHint(active_trigger_ids=("hostility",)),
        previous_trigger_ids=["absurdity"],
    )

    assert [t.trigger_id for t in plan.active_triggers] == ["hostility"]
    assert plan.active_triggers[0].reason == "routing_hint"


def test_no_carryover_when_previous_is_empty() -> None:
    config = _config_with_triggers()
    plan = PersonaTurnPlanner().build_plan(
        config=config,
        user_message="random text with no trigger match",
        scenario="chat",
        task_category="chat",
        previous_trigger_ids=[],
    )
    assert plan.active_triggers == []


def test_carryover_drops_when_trigger_no_longer_in_config() -> None:
    """If the persona config was updated to drop a trigger that previously
    fired, the carryover should silently skip it instead of crashing."""
    config = _config_with_triggers()
    plan = PersonaTurnPlanner().build_plan(
        config=config,
        user_message="hi",
        scenario="chat",
        task_category="chat",
        previous_trigger_ids=["removed_trigger_id"],
    )
    assert plan.active_triggers == []


def test_carryover_suppressed_during_tool_execution() -> None:
    """Task execution should clamp carryover the same way it clamps new
    triggers — no integrating absurdity while editing code."""
    config = _config_with_triggers()
    plan = PersonaTurnPlanner().build_plan(
        config=config,
        user_message="改代码",
        scenario="task",
        task_category="code",
        tools=["edit_file"],
        previous_trigger_ids=["absurdity"],
    )
    assert plan.active_triggers == []


def test_carryover_caps_at_two_entries() -> None:
    config = _config_with_triggers()
    plan = PersonaTurnPlanner().build_plan(
        config=config,
        user_message="hi",
        scenario="chat",
        task_category="chat",
        previous_trigger_ids=["absurdity", "hostility", "noop"],
    )
    assert len(plan.active_triggers) == 2


def test_carryover_returns_typed_active_triggers() -> None:
    config = _config_with_triggers()
    plan = PersonaTurnPlanner().build_plan(
        config=config,
        user_message="hi",
        scenario="chat",
        task_category="chat",
        previous_trigger_ids=["absurdity"],
    )
    assert all(isinstance(t, ActivePersonaTrigger) for t in plan.active_triggers)
