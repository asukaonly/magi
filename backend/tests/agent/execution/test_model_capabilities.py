from __future__ import annotations

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
