from __future__ import annotations

from types import SimpleNamespace

from magi.agent.execution.capability_resolver import CapabilityResolver
from magi.chat.task_agent.coordinator import _attachment_resolver_tools


class _Registry:
    def __init__(self) -> None:
        self.tools = {
            "find-relevant-tools",
            "memory_query",
            "photo_resolver",
            "weather",
        }

    def list_tools(self, *, category=None, enabled_features=None):  # type: ignore[no-untyped-def]
        _ = enabled_features
        if category == "control":
            return []
        return sorted(self.tools)

    def get_tool_info(self, name: str):  # type: ignore[no-untyped-def]
        return {
            "name": name,
            "description": f"{name} capability",
            "category": "test",
            "parameters": [],
        }

    def get_skill_names(self):  # type: ignore[no-untyped-def]
        return ["calendar-review"]

    def get_skill_metadata(self, name: str):  # type: ignore[no-untyped-def]
        if name != "calendar-review":
            return None
        return SimpleNamespace(
            description="Review meetings and calendar availability",
            category="calendar",
            tags=["meeting"],
            argument_hint="date range",
            context="calendar review",
        )

    def get_tool(self, name: str):  # type: ignore[no-untyped-def]
        schema = SimpleNamespace(
            name=name,
            effect_class="read_only",
            effect_replay_policy="read_only",
            dangerous=False,
            requires_auth=False,
            metadata={},
        )
        return SimpleNamespace(get_schema=lambda: schema)


def test_natural_language_discovery_can_expose_a_registered_skill() -> None:
    resolution = CapabilityResolver(_Registry(), top_k=3).resolve(
        user_message="Review my calendar meetings",
    )

    assert "calendar-review" in resolution.initial_exposed_tools
    assert resolution.discovery_scores["calendar-review"] > 0


def test_attachment_resolver_is_pinned_ahead_of_optional_discovery() -> None:
    resolution = CapabilityResolver(_Registry(), top_k=3, max_tools=3).resolve(
        user_message="What was the weather?",
        required_tools=["photo_resolver"],
    )

    assert "photo_resolver" in resolution.pinned_tools
    assert "photo_resolver" in resolution.initial_exposed_tools
    assert set(resolution.resident_tools).issubset(resolution.initial_exposed_tools)


def test_explicit_reply_asset_tools_are_pinned_but_implicit_context_is_not() -> None:
    payload = {
        "asset_refs": [
            {"asset_ref_id": "photo-1", "resolver_tool": "photo_resolver"},
            {"asset_ref_id": "photo-2", "resolver_tool": "photo_resolver"},
        ]
    }
    explicit = SimpleNamespace(
        latest_payload=SimpleNamespace(attachments=[]),
        reply_context=SimpleNamespace(
            is_explicit_reply=True,
            structured_payload=payload,
        ),
    )
    implicit = SimpleNamespace(
        latest_payload=SimpleNamespace(attachments=[]),
        reply_context=SimpleNamespace(
            is_explicit_reply=False,
            structured_payload=payload,
        ),
    )

    assert _attachment_resolver_tools(explicit) == ["photo_resolver"]
    assert _attachment_resolver_tools(implicit) == []


def test_model_without_tool_calls_fails_closed_on_every_candidate() -> None:
    resolution = CapabilityResolver(_Registry()).resolve(
        user_message="Review my calendar",
        required_tools=["photo_resolver"],
        model_supports_tool_calls=False,
    )

    assert resolution.initial_exposed_tools == ()
    assert resolution.required_tools == ("photo_resolver",)
    assert resolution.rejected_tools
    assert {item.reason_code for item in resolution.rejected_tools} == {
        "model_tool_calls_unsupported"
    }


def test_pinned_skill_tool_is_not_a_hard_requirement() -> None:
    resolution = CapabilityResolver(_Registry()).resolve(
        user_message="Review my calendar",
        pinned_tools=["weather"],
        model_supports_tool_calls=False,
    )

    assert resolution.required_tools == ()
    assert resolution.initial_exposed_tools == ()
