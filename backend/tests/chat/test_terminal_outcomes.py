"""Tests for canonical terminal chat outcomes."""

import pytest

from magi.chat.terminal_outcomes import (
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


@pytest.mark.parametrize(
    "status, visible, expected",
    [
        (
            "cancelled",
            "ignored",
            "[Runtime outcome] The turn was cancelled before a final response.",
        ),
        (
            "completed",
            "  ",
            "[Runtime outcome] The turn completed without a visible assistant message.",
        ),
    ],
)
def test_non_answer_terminal_outcomes(status, visible, expected):
    assert model_context_terminal_outcome(status=status, visible_text=visible) == (
        expected,
        "runtime",
    )


@pytest.mark.parametrize("status", ["running", "pending", "unknown", ""])
def test_non_terminal_status_is_rejected(status):
    with pytest.raises(ValueError, match="Unsupported terminal chat status"):
        model_context_terminal_outcome(status=status, visible_text="must not become an answer")
