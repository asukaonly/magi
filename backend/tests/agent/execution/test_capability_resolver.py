from __future__ import annotations

from types import SimpleNamespace

import pytest

from magi.agent.execution.capability_resolver import CapabilityResolver
from magi.agent.execution.function_calling.tools import build_tools_parameter
from magi.chat.task_agent.coordinator import (
    ChatExecutionCoordinator,
    _attachment_resolver_tools,
)
from magi.agent.task_agents.handlers import TurnAdmissionDecision


class _Registry:
    def __init__(self) -> None:
        self.tools = {
            "find-relevant-tools",
            "memory_query",
            "file_write",
            "photo_resolver",
            "verify",
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
            effect_class="local_write" if name == "file_write" else "read_only",
            effect_replay_policy="unknown" if name == "file_write" else "read_only",
            dangerous=False,
            requires_auth=False,
            metadata={},
        )
        return SimpleNamespace(get_schema=lambda: schema)

    def is_skill(self, name: str) -> bool:
        return name == "calendar-review"


def test_nonresident_tools_are_not_exposed_without_an_explicit_runtime_reason() -> None:
    resolution = CapabilityResolver(_Registry()).resolve()

    assert resolution.initial_exposed_tools == (
        "find-relevant-tools",
        "memory_query",
    )
    assert "calendar-review" not in resolution.candidate_tools
    assert "weather" not in resolution.candidate_tools


def test_attachment_resolver_is_pinned_with_resident_tools() -> None:
    resolution = CapabilityResolver(_Registry()).resolve(
        required_tools=["photo_resolver"],
    )

    assert "photo_resolver" in resolution.pinned_tools
    assert "photo_resolver" in resolution.initial_exposed_tools
    assert set(resolution.resident_tools).issubset(resolution.initial_exposed_tools)


def test_pinned_local_write_also_exposes_validation_tool() -> None:
    resolution = CapabilityResolver(_Registry()).resolve(
        pinned_tools=["file_write"],
    )

    assert resolution.initial_exposed_tools == (
        "find-relevant-tools",
        "memory_query",
        "file_write",
        "verify",
    )


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
        pinned_tools=["weather"],
        model_supports_tool_calls=False,
    )

    assert resolution.required_tools == ()
    assert resolution.initial_exposed_tools == ()


@pytest.mark.asyncio
async def test_ordinary_user_text_does_not_change_initial_tool_schema() -> None:
    registry = _Registry()
    coordinator = ChatExecutionCoordinator(
        tool_registry=registry,
        fact_classifier=SimpleNamespace(),
        handler_registry=SimpleNamespace(),
        agent_run_handler=SimpleNamespace(),
    )

    def context(message: str) -> SimpleNamespace:
        return SimpleNamespace(
            latest_user_message=message,
            latest_payload=SimpleNamespace(skill_invocation=None, attachments=[]),
            reply_context=None,
            recent_tool_errors=[],
            core_model_supports_tool_calls=True,
        )

    first = await coordinator.resolve_capabilities(
        context("只回复收到，不要使用工具。"),
        TurnAdmissionDecision(run_kind="chat", execution_mode=None),
    )
    second = await coordinator.resolve_capabilities(
        context("解释 HTTPS，不需要搜索。"),
        TurnAdmissionDecision(run_kind="chat", execution_mode=None),
    )

    assert first.tools == second.tools
    assert build_tools_parameter(registry, first.tools) == build_tools_parameter(
        registry,
        second.tools,
    )
