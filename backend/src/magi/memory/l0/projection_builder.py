"""Projection helpers for prompt-facing L0 summaries."""

from __future__ import annotations

from typing import Any

from .contracts import L0ExecutionSummary


def build_execution_summary(
    *,
    run: dict[str, Any] | None,
    pending_turns: list[dict[str, Any]],
    accepted_results: list[dict[str, Any]] | None = None,
) -> L0ExecutionSummary | None:
    """Build a prompt-safe execution summary from raw execution-lane state."""
    if not isinstance(run, dict):
        return None

    current_revision = int(run.get("revision") or 0)
    current_revision_pending_turns = [
        item
        for item in pending_turns
        if (
            isinstance(item, dict)
            and item.get("revision") is not None
            and int(item["revision"]) == current_revision
        )
    ]
    current_revision_results = [
        item
        for item in (accepted_results or [])
        if (
            isinstance(item, dict)
            and item.get("revision") is not None
            and int(item["revision"]) == current_revision
        )
    ]
    latest_pending_turn = current_revision_pending_turns[-1] if current_revision_pending_turns else None
    status = str(run.get("status") or "").strip()
    waiting_reason = (
        "user_replan_pending"
        if current_revision_pending_turns
        else "checkpoint_ready"
        if current_revision_results
        else "external_result"
        if status == "running"
        else None
    )
    return L0ExecutionSummary(
        active_run_summary=str(run.get("root_user_message") or "").strip(),
        awaiting_external_result=waiting_reason == "external_result",
        waiting_reason=waiting_reason,
        latest_user_augmentation_summary=(
            str(latest_pending_turn.get("content") or "").strip()
            if isinstance(latest_pending_turn, dict)
            else None
        ),
    )
