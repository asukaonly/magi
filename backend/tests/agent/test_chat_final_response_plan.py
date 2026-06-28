from __future__ import annotations

from types import SimpleNamespace

from magi.chat.task_agent.postprocess.final_response_plan import (
    build_final_response_delivery_plan,
)


def test_final_response_delivery_plan_uses_persisted_final_message() -> None:
    message = SimpleNamespace(
        message_id="msg-final",
        message_kind="assistant_final",
        persona_id="persona-seven",
    )

    plan = build_final_response_delivery_plan(
        response_text="done",
        ux_plan={"assistant_surface_mode": "final_only"},
        notification_message=message,
        fallback_persona_id="persona-fallback",
        resolve_reaction_text=lambda ux_plan, fallback: fallback,
    )

    assert plan.response_text == "done"
    assert plan.message_id == "msg-final"
    assert plan.message_kind == "assistant_final"
    assert plan.persona_id == "persona-seven"
    assert plan.final_message is message


def test_reaction_only_delivery_plan_uses_reaction_surface() -> None:
    message = SimpleNamespace(
        message_id="msg-final",
        message_kind="assistant_final",
        persona_id="persona-seven",
    )

    plan = build_final_response_delivery_plan(
        response_text="收到啦",
        ux_plan={"assistant_surface_mode": "reaction_only", "reaction_style": "acknowledge"},
        notification_message=message,
        fallback_persona_id="persona-active",
        resolve_reaction_text=lambda ux_plan, fallback: "👌",
    )

    assert plan.response_text == "👌"
    assert plan.message_id is None
    assert plan.message_kind == "assistant_reaction"
    assert plan.persona_id == "persona-active"
    assert plan.final_message is None
