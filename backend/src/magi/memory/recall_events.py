"""Scope and correction checks for expanded or directly read L1 evidence."""

from typing import Any

from .evidence import USER_VISIBLE_L1_RETRIEVAL_SCOPES
from .hybrid_retrieval.correction_evidence_governance import decide_l1_correction_evidence
from .hybrid_retrieval.models import RetrievalPayload, RetrievalQuery


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


async def read_recall_event(memory: Any, request: RetrievalQuery) -> RetrievalPayload:
    """Read an authorized original in bounded chunks, with governed neighbors."""
    from .hybrid_retrieval.intent_time import parse_raw_time_range
    from .hybrid_retrieval.timeline_condense import build_timeline_summary

    if not request.user_id or not request.read_event_id or request.read_offset < 0:
        raise ValueError("An event read requires a principal, a reference and a nonnegative offset")
    mode = request.query_mode or "episode_recall"
    historical = mode in {"episode_recall", "experience_recall", "event_stream"}
    parsed = parse_raw_time_range(request.time_range)
    if request.time_range and parsed is None:
        raise ValueError("Invalid time constraint for an original memory read")
    time_range = {"start": parsed.start, "end": parsed.end if parsed.end is not None else parsed.as_of} if parsed else {}
    rows = await memory.l1.query_events(
        event_id=request.read_event_id, user_id=request.user_id,
        l1_retrieval_scopes=list(USER_VISIBLE_L1_RETRIEVAL_SCOPES), limit=1,
        include_embedding_fields=False,
    )
    rows = await govern_recall_events(memory, rows, request, time_range=time_range, historical=historical)
    payload = RetrievalPayload(trace={"query_mode": mode, "resolved_time_range": time_range})
    if not rows:
        return payload
    event = rows[0]
    content = str(event.get("content") or "")
    if request.read_offset > len(content):
        raise ValueError("Read offset exceeds the current record length")
    end = min(request.read_offset + 6000, len(content))
    primary = {**event, "content": content[request.read_offset:end],
               "read": {"offset": request.read_offset, "next_offset": end if end < len(content) else None,
                        "total_chars": len(content)}}
    payload.l1_events = [primary]
    neighbors = []
    if event.get("session_id") and event.get("session_seq") is not None:
        neighbors = await memory.l1.query_session_event_window(
            session_id=event["session_id"], center_session_seq=event["session_seq"], window=1,
            user_id=request.user_id, include_embedding_fields=False,
        )
        neighbors = await govern_recall_events(memory, neighbors, request, time_range=time_range, historical=historical)
    # Keep the original chunk once; the surrounding records remain labeled context.
    neighbors = [item for item in neighbors if item.get("event_id") != event["event_id"]]
    bundle = {"hit_event_ids": [event["event_id"]], "answer_events": neighbors, "events": neighbors}
    payload.l1_evidence_bundles = [bundle]
    payload.l1_timeline_summary = build_timeline_summary(question=request.query, evidence_bundles=[bundle])
    return payload
