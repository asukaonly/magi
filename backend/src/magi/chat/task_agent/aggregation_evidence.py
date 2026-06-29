"""Rendering helpers for chat orchestration aggregation evidence."""

from __future__ import annotations

from typing import Any


def build_aggregation_evidence_dossier(payload: dict[str, Any]) -> str:
    """Render worker evidence into the final aggregation input dossier."""
    lines: list[str] = []
    completed = _payload_list(payload, "completed_subtasks")
    failed = _payload_list(payload, "failed_subtasks")

    _append_completed_analyses(lines, completed)
    _append_remaining_unverified_areas(lines, failed)

    return "\n".join(line for line in lines if line is not None).strip()


def _payload_list(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    return value if isinstance(value, list) else []


def _payload_dict(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def _append_completed_analyses(lines: list[str], completed: list[Any]) -> None:
    lines.append("### Completed Analyses")
    if not completed:
        lines.append("- No completed subtask results were available.")
        lines.append("")
        return

    for index, item in enumerate(completed, start=1):
        if not isinstance(item, dict):
            continue
        _append_completed_analysis(lines, index, item)


def _append_completed_analysis(lines: list[str], index: int, item: dict[str, Any]) -> None:
    description = str(item.get("description") or f"Completed subtask {index}").strip()
    result = _payload_dict(item, "result")

    lines.append(f"#### {index}. {description}")
    summary = str(result.get("summary") or "").strip()
    if summary:
        lines.append(f"Summary: {summary}")

    _append_findings(lines, _payload_list(result, "findings"))
    _append_evidence(lines, _payload_list(result, "evidence"))
    _append_text_list(lines, "Open Gaps:", _payload_list(result, "gaps"))
    _append_text_list(lines, "Suggested Follow-ups:", _payload_list(result, "next_steps"))
    lines.append("")


def _append_findings(lines: list[str], findings: list[Any]) -> None:
    if not findings:
        return

    lines.append("Key Findings:")
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        title = str(finding.get("title") or "Finding").strip()
        detail = str(finding.get("detail") or "").strip()
        why = str(finding.get("why_it_matters") or "").strip()
        path = str(finding.get("path") or "").strip()
        parts = [f"- {title}"]
        if detail:
            parts.append(detail)
        if why:
            parts.append(f"Why it matters: {why}")
        if path:
            parts.append(f"Evidence path: {path}")
        lines.append(" | ".join(parts))


def _append_evidence(lines: list[str], evidence_items: list[Any]) -> None:
    if not evidence_items:
        return

    lines.append("Evidence:")
    for evidence in evidence_items:
        if not isinstance(evidence, dict):
            continue
        path = str(evidence.get("path") or "").strip()
        detail = str(evidence.get("detail") or "").strip()
        rendered = path or "(no path provided)"
        if detail:
            rendered = f"{rendered} — {detail}"
        lines.append(f"- {rendered}")


def _append_text_list(lines: list[str], heading: str, items: list[Any]) -> None:
    if not items:
        return

    lines.append(heading)
    for item in items:
        text = str(item or "").strip()
        if text:
            lines.append(f"- {text}")


def _append_remaining_unverified_areas(lines: list[str], failed: list[Any]) -> None:
    lines.append("### Remaining Unverified Areas")
    if not failed:
        lines.append("- None")
        return

    for item in failed:
        if not isinstance(item, dict):
            continue
        _append_failed_subtask(lines, item)


def _append_failed_subtask(lines: list[str], item: dict[str, Any]) -> None:
    description = str(item.get("description") or "Unknown failed subtask").strip()
    failure_reason = str(item.get("failure_reason") or "UNKNOWN").strip()
    result = _payload_dict(item, "result")
    failure_details = _payload_dict(item, "failure_details")

    lines.append(f"- {description} | Failure reason: {failure_reason}")
    _append_failure_summary(lines, result, failure_details)
    _append_worker_gaps(lines, _payload_list(result, "gaps"))
    _append_tool_failures(lines, _payload_list(failure_details, "tool_failures"))


def _append_failure_summary(
    lines: list[str],
    result: dict[str, Any],
    failure_details: dict[str, Any],
) -> None:
    summary = str(result.get("summary") or failure_details.get("error_text") or "").strip()
    if summary:
        lines.append(f"  - Failure detail: {summary[:500]}")


def _append_worker_gaps(lines: list[str], worker_gaps: list[Any]) -> None:
    for gap in worker_gaps[:3]:
        gap_text = str(gap or "").strip()
        if gap_text:
            lines.append(f"  - Gap: {gap_text}")


def _append_tool_failures(lines: list[str], tool_failures: list[Any]) -> None:
    for failure in tool_failures[:3]:
        if not isinstance(failure, dict):
            continue
        tool_name = str(failure.get("tool_name") or "unknown").strip()
        error_code = str(failure.get("error_code") or "UNKNOWN").strip()
        error = str(failure.get("error") or "").strip()
        line = f"  - Tool failure: {tool_name} | {error_code}"
        if error:
            line += f" | {error[:300]}"
        lines.append(line)
        _append_tool_failure_diagnostics(lines, _payload_dict(failure, "diagnostics"))


def _append_tool_failure_diagnostics(lines: list[str], diagnostics: dict[str, Any]) -> None:
    user_message = str(diagnostics.get("user_message_template") or "").strip()
    next_action = str(diagnostics.get("next_action") or "").strip()
    if user_message:
        lines.append(f"    Suggested user-facing explanation: {user_message[:300]}")
    if next_action:
        lines.append(f"    Next action: {next_action}")
