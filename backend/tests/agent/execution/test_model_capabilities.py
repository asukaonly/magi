from __future__ import annotations

import pytest

from types import SimpleNamespace

from magi.agent.execution.model_capabilities import ModelCapabilityProfile


@pytest.mark.parametrize(
    "schema_tokens,expected", [(99, None), (100, None), (101, "tool_schema_token_limit_exceeded")]
)
def test_schema_token_limit_is_inclusive_at_boundary(schema_tokens, expected):
    assert (
        ModelCapabilityProfile(max_schema_tokens=100).validate_run(
            has_images=False, tool_count=2, schema_tokens=schema_tokens
        )
        == expected
    )


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
