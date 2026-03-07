"""Markdown aggregation for ExploreTaskAgent."""
from __future__ import annotations

from typing import Any, Optional

from ...orchestration import TaskOrchestrationState

_CANONICAL_REPO_SECTIONS = {
    "Map repository layout": "Repository Layout",
    "Identify technology stack": "Technology Stack",
    "Analyze frontend structure": "Frontend Structure",
    "Analyze backend modules": "Backend Modules",
    "Inspect project progress": "Project Progress",
}


class ExploreAggregationService:
    """Builds deterministic Markdown dossiers from Explore worker results."""

    async def aggregate_orchestration(self, state: TaskOrchestrationState) -> str:
        dossier = self.render_markdown_dossier(state)
        state.aggregated_markdown = dossier
        return dossier

    def render_markdown_dossier(self, state: TaskOrchestrationState) -> str:
        completed = {
            item.description: item
            for item in state.subtasks
            if item.status == "completed" and isinstance(item.worker_result, dict)
        }
        failed = [item for item in state.subtasks if item.status == "failed"]
        evidence_lines: list[str] = []
        gap_lines: list[str] = []
        next_steps: list[str] = []
        summary_lines: list[str] = []

        for item in state.subtasks:
            worker_result = item.worker_result if isinstance(item.worker_result, dict) else {}
            summary = str(worker_result.get("summary", "")).strip()
            if summary and item.status == "completed":
                summary_lines.append(f"- **{item.description}:** {summary}")
            if item.status == "failed":
                gap_lines.append(f"- {item.description}: {item.failure_reason or 'Not completed in this run.'}")
            for gap in worker_result.get("gaps", []) if isinstance(worker_result, dict) else []:
                text = str(gap).strip()
                if text:
                    gap_lines.append(f"- {item.description}: {text}")
            for step in worker_result.get("next_steps", []) if isinstance(worker_result, dict) else []:
                text = str(step).strip()
                if text and text not in next_steps:
                    next_steps.append(text)
            for evidence in worker_result.get("evidence", []) if isinstance(worker_result, dict) else []:
                if not isinstance(evidence, dict):
                    continue
                path = str(evidence.get("path", "")).strip()
                detail = str(evidence.get("detail", "")).strip()
                if path and detail:
                    evidence_lines.append(f"- `{path}`: {detail}")

        lines = [
            "# Request",
            state.root_user_message,
            "",
            "# Exploration Summary",
            "\n".join(summary_lines) if summary_lines else "- No completed exploration sections yet.",
            "",
        ]

        for description, heading in _CANONICAL_REPO_SECTIONS.items():
            lines.extend(
                [
                    f"## {heading}",
                    self._render_subtask_section(completed.get(description), failed, description),
                    "",
                ]
            )

        lines.extend(
            [
                "## Confirmed Evidence",
                "\n".join(evidence_lines) if evidence_lines else "- No confirmed evidence was captured.",
                "",
                "## Gaps and Unverified Areas",
                "\n".join(gap_lines) if gap_lines else "- No explicit gaps were reported.",
                "",
                "## Recommended Next Steps",
                "\n".join(f"- {item}" for item in next_steps) if next_steps else "- No follow-up steps were suggested.",
            ]
        )
        return "\n".join(lines).strip()

    def _render_subtask_section(
        self,
        subtask: Optional[Any],
        failed: list[Any],
        description: str,
    ) -> str:
        if subtask is None:
            failed_item = next((item for item in failed if item.description == description), None)
            if failed_item is not None:
                return f"- Not fully verified. Failure reason: {failed_item.failure_reason or 'Unknown failure.'}"
            return "- Not explored in this run."

        worker_result = subtask.worker_result if isinstance(subtask.worker_result, dict) else {}
        result_lines = [str(worker_result.get("summary", "")).strip() or "- Completed without a summary."]
        findings = worker_result.get("findings")
        if isinstance(findings, list):
            for finding in findings:
                if not isinstance(finding, dict):
                    continue
                title = str(finding.get("title", "")).strip()
                detail = str(finding.get("detail", "")).strip()
                path = str(finding.get("path", "")).strip()
                why = str(finding.get("why_it_matters", "")).strip()
                if title and detail:
                    line = f"- **{title}:** {detail}"
                    if path:
                        line += f" (`{path}`)"
                    if why:
                        line += f" - {why}"
                    result_lines.append(line)
        return "\n".join(result_lines)
