"""Conflict arbitration prompt execution for L2."""

from __future__ import annotations

from ...llm import LLMScenario
from .llm_priority import l2_llm_priority_for_event_window
from .models import (
    ContradictionHint,
    L2CandidateSet,
    L2ConflictArbitrationResult,
    L2EventWindow,
    L2ExistingRecord,
    L2SourceEvent,
)
from .pipeline.prompts import (
    CONFLICT_ARBITRATION_SYSTEM_PROMPT,
    render_conflict_arbitration_prompt,
)


class L2LLMConflictMixin:
    """Execute L2 graph/assertion conflict arbitration prompts."""

    async def arbitrate_conflict(
        self,
        *,
        new_event_window: L2EventWindow,
        new_candidates: L2CandidateSet,
        contradiction_hints: list[ContradictionHint],
        existing_records: list[L2ExistingRecord],
        source_events: list[L2SourceEvent],
    ) -> L2ConflictArbitrationResult | None:
        event_ids = list(new_event_window.event_ids)
        contradiction_hint_payload = [hint.to_dict() for hint in contradiction_hints]
        payload = await self._generate_json(
            system_prompt=CONFLICT_ARBITRATION_SYSTEM_PROMPT,
            prompt=render_conflict_arbitration_prompt(
                new_event_window=new_event_window,
                new_candidates=new_candidates,
                contradiction_hints=contradiction_hint_payload,
                existing_records=existing_records,
                source_events=source_events,
            ),
            request_kind="memory:l2_conflict_arbitration",
            turn_id=str(event_ids[0]) if isinstance(event_ids, list) and event_ids else None,
            session_id=self._non_empty_text(new_event_window.summary.session_id),
            log_context={
                "event_ids": event_ids if isinstance(event_ids, list) else [],
                "contradiction_hint_count": len(contradiction_hint_payload),
                "existing_record_count": len(existing_records),
            },
            scenario=LLMScenario.CORE,
            disable_thinking=False,
            priority=l2_llm_priority_for_event_window(new_event_window),
            required_fields={"decision": str},
        )
        decision = str(payload.get("decision") or "").strip()
        if decision not in {"keep_new", "keep_existing", "mark_evolution"}:
            return None
        return L2ConflictArbitrationResult(
            decision=decision,
            winning_record_ids=[
                str(item) for item in payload.get("winning_record_ids", []) if str(item).strip()
            ],
            superseded_record_ids=[
                str(item) for item in payload.get("superseded_record_ids", []) if str(item).strip()
            ],
            reason=str(payload.get("reason") or "").strip(),
        )


__all__ = ["L2LLMConflictMixin"]
