from __future__ import annotations

import pytest
from pydantic import ValidationError

from magi.config.memory_models import MemoryL0Settings


def test_l0_attention_update_defaults() -> None:
    settings = MemoryL0Settings()

    assert settings.attention_update_turn_threshold == 3
    assert settings.attention_update_idle_seconds == 30
    assert settings.attention_update_max_delay_seconds == 90
    assert "runtime_replay_include_l0_only" not in settings.model_dump()


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("attention_update_turn_threshold", 0),
        ("attention_update_turn_threshold", 21),
        ("attention_update_idle_seconds", 0),
        ("attention_update_idle_seconds", 301),
        ("attention_update_max_delay_seconds", 0),
        ("attention_update_max_delay_seconds", 601),
    ],
)
def test_l0_attention_update_fields_enforce_bounds(
    field_name: str,
    invalid_value: int,
) -> None:
    with pytest.raises(ValidationError):
        MemoryL0Settings(**{field_name: invalid_value})


def test_l0_attention_update_max_delay_cannot_precede_idle_delay() -> None:
    with pytest.raises(
        ValidationError,
        match=(
            "attention_update_max_delay_seconds must be greater than or equal to "
            "attention_update_idle_seconds"
        ),
    ):
        MemoryL0Settings(
            attention_update_idle_seconds=120,
            attention_update_max_delay_seconds=90,
        )
