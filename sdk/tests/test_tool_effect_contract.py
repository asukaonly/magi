from __future__ import annotations

import pytest
from pydantic import ValidationError

from magi_plugin_sdk.tools import ToolSchema


def test_tool_effect_policy_defaults_to_fail_closed_unknown() -> None:
    schema = ToolSchema(name="example", description="example", category="test")

    assert schema.effect_replay_policy == "unknown"
    assert schema.effect_idempotency_key_parameter is None


def test_idempotency_key_policy_preserves_declared_parameter() -> None:
    schema = ToolSchema(
        name="example",
        description="example",
        category="test",
        effect_replay_policy="idempotent_with_key",
        effect_idempotency_key_parameter="request_id",
    )

    assert schema.effect_replay_policy == "idempotent_with_key"
    assert schema.effect_idempotency_key_parameter == "request_id"


def test_invalid_tool_effect_policy_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ToolSchema(
            name="example",
            description="example",
            category="test",
            effect_replay_policy="always_retry",
        )
