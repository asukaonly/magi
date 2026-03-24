"""Projection helpers for prompt-facing L0 summaries."""

from __future__ import annotations

from typing import Any

from .contracts import L0ExecutionSummary


def build_execution_summary(
    *,
    run: dict[str, Any] | None,
    pending_turns: list[dict[str, Any]],
) -> L0ExecutionSummary | None:
    """Build a prompt-safe execution summary from raw execution-lane state."""
    if not isinstance(run, dict):
        return None

    latest_pending_turn = pending_turns[-1] if pending_turns else None
    current_revision = int(run.get("revision") or 0)
    has_current_revision_pending_turns = any(
        isinstance(item, dict) and int(item.get("revision") or -1) == current_revision
        for item in pending_turns
    )
    return L0ExecutionSummary(
        active_run_summary=str(run.get("root_user_message") or "").strip(),
        awaiting_external_result=(
            str(run.get("status") or "").strip() == "running"
            and not has_current_revision_pending_turns
        ),
        latest_user_augmentation_summary=(
            str(latest_pending_turn.get("content") or "").strip()
            if isinstance(latest_pending_turn, dict)
            else None
        ),
    )
