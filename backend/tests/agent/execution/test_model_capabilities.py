from __future__ import annotations

from types import SimpleNamespace

from magi.agent.execution.model_capabilities import ModelCapabilityProfile


def test_schema_token_limit_rejects_oversized_tool_payload() -> None:
    profile = ModelCapabilityProfile(max_schema_tokens=100)

    issue = profile.validate_run(
        has_images=False,
        tool_count=2,
        schema_tokens=101,
    )

    assert issue == "tool_schema_token_limit_exceeded"


def test_schema_token_limit_allows_payload_at_boundary() -> None:
    profile = ModelCapabilityProfile(max_schema_tokens=100)

    issue = profile.validate_run(
        has_images=False,
        tool_count=2,
        schema_tokens=100,
    )

    assert issue is None


def test_active_model_context_projects_declared_schema_limits() -> None:
    profile = ModelCapabilityProfile.from_model_context(
        SimpleNamespace(
            supports_images=False,
            supports_tool_calls=True,
            supports_images_with_tools=False,
            supports_parallel_tools=False,
            max_tool_schemas=3,
            max_schema_tokens=100,
        )
    )

    assert profile.max_tool_schemas == 3
    assert profile.max_schema_tokens == 100
    assert (
        profile.validate_run(
            has_images=False,
            tool_count=4,
            schema_tokens=50,
        )
        == "tool_schema_limit_exceeded"
    )
