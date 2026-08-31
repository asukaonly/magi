"""Tests for terminal chat trace status normalization."""

from types import SimpleNamespace

import pytest

from magi.runtime_trace.chat_trace.utils import (
    derive_children_status,
    is_terminal_status,
    normalize_status,
)


@pytest.mark.parametrize(
    "status",
    ["blocked", "cancelled", "completed", "failed", "interrupted", "merged"],
)
def test_terminal_chat_trace_statuses_remain_terminal(status: str) -> None:
    assert normalize_status(status) == status
    assert is_terminal_status(status)


def test_failed_child_is_not_hidden_by_completed_sibling() -> None:
    children = [
        SimpleNamespace(status="completed"),
        SimpleNamespace(status="failed"),
    ]

    assert derive_children_status(children) == "failed"
