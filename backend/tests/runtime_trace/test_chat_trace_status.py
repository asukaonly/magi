"""Tests for terminal chat trace status normalization."""

from types import SimpleNamespace

import pytest

from magi.runtime_trace.chat_trace.utils import (
    derive_children_status,
    is_terminal_status,
    normalize_status,
)


@pytest.mark.parametrize(
    "raw,normalized,terminal",
    [
        ("blocked", "blocked", True),
        ("cancelled", "cancelled", True),
        ("completed", "completed", True),
        ("failed", "failed", True),
        ("interrupted", "interrupted", True),
        ("merged", "merged", True),
        ("pending", "pending", False),
        ("running", "running", False),
        ("unknown", "running", False),
        ("TIMED_OUT", "failed", True),
    ],
)
def test_normalized_child_status_preserves_terminal_and_active_semantics(raw, normalized, terminal):
    status = normalize_status(raw)
    assert status == normalized
    assert is_terminal_status(status) is terminal
    assert derive_children_status(
        [SimpleNamespace(status="completed"), SimpleNamespace(status=status)]
    ) == (normalized if terminal else "running")


def test_failed_child_is_not_hidden_by_completed_sibling() -> None:
    children = [
        SimpleNamespace(status="completed"),
        SimpleNamespace(status="failed"),
    ]

    assert derive_children_status(children) == "failed"
