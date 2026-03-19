"""Rule-first builder for task-driven L3 reflection candidates."""

from __future__ import annotations

from .models import L3Candidate, TaskOutcomePacket


class TaskReflectionService:
    """Builds L3 candidates from user-facing task outcomes."""

    async def build_candidate(self, packet: TaskOutcomePacket) -> L3Candidate | None:
        """Convert a task outcome packet into an L3 candidate when it has user value."""
        if packet.task_kind == "orchestration_task":
            return None
        if not packet.evidence_event_ids:
            return None

        content_parts: list[str] = []
        subtypes: list[str] = []

        if packet.user_goal:
            content_parts.append(f"User goal: {packet.user_goal}")
        if packet.result_summary:
            content_parts.append(packet.result_summary)
        if packet.decisions:
            subtypes.append("decision_summary")
            content_parts.extend(str(item.get("content", "")).strip() for item in packet.decisions if str(item.get("content", "")).strip())
        if packet.constraints:
            subtypes.append("constraint_summary")
            content_parts.extend(str(item.get("content", "")).strip() for item in packet.constraints if str(item.get("content", "")).strip())
        if packet.blockers:
            subtypes.append("blocker_pattern")
            content_parts.extend(str(item.get("content", "")).strip() for item in packet.blockers if str(item.get("content", "")).strip())
        if packet.next_steps:
            subtypes.append("next_step_reflection")
            content_parts.append("Next steps: " + "; ".join(step for step in packet.next_steps if step.strip()))

        content = " ".join(part for part in content_parts if part).strip()
        if not content:
            return None

        return L3Candidate(
            summary_type="insight",
            summary_category="task_reflection",
            content=content,
            source_event_ids=list(packet.evidence_event_ids),
            subtypes=subtypes,
        )
