"""Tests for canonical terminal chat outcomes."""

import pytest

from magi.chat.terminal_outcomes import (
    PRE_SUCCESS_TERMINAL_CHAT_STATUSES,
    TERMINAL_CHAT_STATUSES,
    model_context_terminal_outcome,
)


@pytest.mark.parametrize("status", ["blocked", "failed", "interrupted", "merged"])
def test_unsuccessful_turns_become_runtime_outcomes(status: str) -> None:
    text, kind = model_context_terminal_outcome(
        status=status,
        visible_text="presentation-only error",
        error_text="reason",
    )

    assert kind == "runtime"
    assert f"status '{status}'" in text
    assert text.endswith("Reason: reason")


def test_completed_visible_turn_becomes_assistant_outcome() -> None:
    assert model_context_terminal_outcome(
        status="completed",
        visible_text="accepted answer",
    ) == ("accepted answer", "assistant")


def test_terminal_status_vocabulary_has_one_canonical_definition() -> None:
    assert TERMINAL_CHAT_STATUSES == {
        "blocked",
        "cancelled",
        "completed",
        "failed",
        "interrupted",
        "merged",
    }
    assert PRE_SUCCESS_TERMINAL_CHAT_STATUSES == TERMINAL_CHAT_STATUSES - {"completed"}
