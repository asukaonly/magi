"""Scope and correction checks for expanded or directly read L1 evidence."""

from typing import Any

from .evidence import USER_VISIBLE_L1_RETRIEVAL_SCOPES
from .hybrid_retrieval.correction_evidence_governance import decide_l1_correction_evidence
from .hybrid_retrieval.models import RetrievalQuery


async def govern_recall_events(
    memory: Any, events: list[dict[str, Any]], request: RetrievalQuery,
    *, time_range: dict[str, Any], historical: bool,
) -> list[dict[str, Any]]:
    """Expand only visible, same-principal records; never promote corrected facts."""
    scopes = set(USER_VISIBLE_L1_RETRIEVAL_SCOPES) if historical else {"fact_authoritative"}
    selected = [event for event in events
        if event.get("event_id") and event.get("deleted_at") is None
        and event.get("l1_retrieval_scope") in scopes
        and (not request.user_id or event.get("user_id") == request.user_id)
        and (not request.session_id or event.get("session_id") == request.session_id)
        and (not request.source_filters or event.get("source") in request.source_filters)
        and (not request.domain_filters or event.get("memory_domain") in request.domain_filters)
        and (time_range.get("start") is None or float(event.get("timestamp") or 0) >= time_range["start"])
        and (time_range.get("end") is None or float(event.get("timestamp") or 0) <= time_range["end"])]
    if not selected:
        return []
    decision = await decide_l1_correction_evidence(memory.l2, [str(event["event_id"]) for event in selected])
    if decision.drop_all:
        return []
    return [
        {**event,
         **({"evidence_semantics": "historical_record"} if historical else {}),
         **({"correction_status": "later_corrected"} if event["event_id"] in decision.blocked_event_ids else {})}
        for event in selected if historical or event["event_id"] not in decision.blocked_event_ids
    ]
