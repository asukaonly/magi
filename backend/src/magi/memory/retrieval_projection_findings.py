"""Finding projection helpers for historical recall payloads."""

from __future__ import annotations

from typing import Any

from .hybrid_retrieval.models import RetrievalPayload, RetrievalQuery
from .retrieval_projection_summary import is_list_like_query, split_relationship_statement


def build_findings(payload: RetrievalPayload, request: RetrievalQuery) -> list[dict[str, Any]]:
    query_mode = str(request.query_mode or "").strip()

    if query_mode in {"exact_fact", "current_state"}:
        event_findings = _project_events(payload.l1_events)
        relationship_findings = _project_relationships(payload.l2_relationships)
        if relationship_findings:
            if query_mode == "exact_fact":
                sorted_relationships = _sort_preference_relationship_findings(
                    relationship_findings, payload=payload, request=request,
                )
                preserve_count = _preserved_l1_event_count(request=request, event_findings=event_findings)
                if preserve_count > 0:
                    return _merge_exact_fact_findings(
                        event_findings,
                        sorted_relationships,
                        limit=request.limit,
                        preserved_event_count=preserve_count,
                    )
                return sorted_relationships
            return relationship_findings
        assertion_findings = _project_assertions(payload.l2_assertions)
        if assertion_findings:
            preserve_count = _preserved_l1_event_count(request=request, event_findings=event_findings)
            if query_mode == "exact_fact" and preserve_count > 0:
                return _merge_exact_fact_findings(
                    event_findings,
                    assertion_findings,
                    limit=request.limit,
                    preserved_event_count=preserve_count,
                )
            return assertion_findings
        return event_findings

    if query_mode == "strategy":
        findings = _project_procedures(payload.l4_procedures)
        if findings:
            return findings
        findings = _project_reflections(payload.l3_reflections)
        if findings:
            return findings
        return _project_events(payload.l1_events)

    if query_mode == "summary":
        findings = _project_reflections(payload.l3_reflections)
        if findings:
            return findings
        return _project_events(payload.l1_events)

    if query_mode == "activity_summary":
        findings = _project_reflections(payload.l3_reflections)
        if findings:
            return findings
        return _project_events(payload.l1_events)

    findings = _project_events(payload.l1_events)
    if findings:
        return findings
    findings = _project_relationships(payload.l2_relationships)
    if findings:
        return findings
    return _project_assertions(payload.l2_assertions)


def _project_relationships(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        subject = str(item.get("subject") or item.get("subject_id") or "").strip()
        predicate = str(item.get("predicate") or "").strip()
        object_value = str(item.get("object") or item.get("object_id") or "").strip()
        if not subject or not predicate or not object_value:
            continue
        finding: dict[str, Any] = {
            "kind": "relationship",
            "statement": f"{subject} {predicate} {object_value}",
            "source_layer": "L2",
            "confidence": item.get("confidence"),
            "status": item.get("status"),
            "occurred_at": item.get("first_observed_at"),
            "updated_at": item.get("updated_at"),
        }
        evidence_text = str(item.get("evidence_text") or "").strip()
        if evidence_text:
            finding["evidence_text"] = evidence_text
        findings.append(finding)
    return findings


def _sort_preference_relationship_findings(
    findings: list[dict[str, Any]],
    *,
    payload: RetrievalPayload,
    request: RetrievalQuery,
) -> list[dict[str, Any]]:
    answer_kind = _infer_answer_kind(payload=payload, request=request)
    polarity = _infer_query_polarity(request.query)

    def _sort_key(item: dict[str, Any]) -> tuple[int, float, float]:
        statement = str(item.get("statement") or "").strip()
        _, predicate, _ = split_relationship_statement(statement)
        priority = _predicate_priority(predicate=predicate, answer_kind=answer_kind, polarity=polarity)
        confidence = float(item.get("confidence") or 0.0)
        updated_at = float(item.get("updated_at") or 0.0)
        return (priority, -confidence, -updated_at)

    return sorted(findings, key=_sort_key)


def _infer_answer_kind(*, payload: RetrievalPayload, request: RetrievalQuery) -> str:
    l2_trace = payload.trace.get("l2_query_trace")
    if isinstance(l2_trace, dict):
        semantic_frame = l2_trace.get("semantic_frame")
        if isinstance(semantic_frame, dict):
            answer_kind = str(semantic_frame.get("answer_kind") or "").strip()
            if answer_kind:
                return answer_kind

    findings_answer_kind = _infer_answer_kind_from_relationships(payload.l2_relationships)
    if findings_answer_kind is not None:
        return findings_answer_kind

    return "unknown"


def _infer_answer_kind_from_relationships(items: list[dict[str, Any]]) -> str | None:
    kind_by_entity_type = {
        "topic": "topic",
        "software": "software",
        "place": "place",
        "person": "creator",
        "group": "creator",
        "organization": "creator",
        "presence": "creator",
    }
    inferred_kinds: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        object_value = str(item.get("object") or item.get("object_id") or "").strip()
        if ":" not in object_value:
            continue
        entity_type, _, _ = object_value.partition(":")
        answer_kind = kind_by_entity_type.get(entity_type)
        if answer_kind:
            inferred_kinds.append(answer_kind)

    if not inferred_kinds:
        return None

    unique_kinds = list(dict.fromkeys(inferred_kinds))
    if len(unique_kinds) == 1:
        return unique_kinds[0]
    return None


def _infer_query_polarity(query: str) -> str:
    query_lower = str(query or "").strip().lower()
    if any(token in query_lower for token in ("讨厌", "不喜欢", "dislike", "hate")):
        return "negative"
    return "positive"


def _predicate_priority(*, predicate: str, answer_kind: str, polarity: str) -> int:
    predicate_upper = str(predicate or "").strip().upper()
    if polarity == "negative":
        negative_priority = {"DISLIKES": 0, "LIKES": 1, "INTERESTED_IN": 2, "FOLLOWS": 3, "USES": 4, "VISITED": 4}
        return negative_priority.get(predicate_upper, 99)

    priority_map = {
        "creator": {"FOLLOWS": 0, "LIKES": 1, "INTERESTED_IN": 2, "DISLIKES": 3},
        "place": {"LIKES": 0, "VISITED": 1, "DISLIKES": 2},
        "topic": {"INTERESTED_IN": 0, "LIKES": 1, "DISLIKES": 2},
        "software": {"LIKES": 0, "USES": 1, "DISLIKES": 2},
    }
    return priority_map.get(answer_kind, {}).get(predicate_upper, 99)


def _project_assertions(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        subject = str(item.get("subject") or item.get("entity_id") or "").strip()
        predicate = str(item.get("predicate") or item.get("trait_name") or item.get("trait_family") or "").strip()
        value = str(
            item.get("claim")
            or item.get("content")
            or item.get("trait_value")
            or item.get("target_entity_id")
            or ""
        ).strip()
        if not subject or not predicate or not value:
            continue
        findings.append(
            {
                "kind": "assertion",
                "statement": f"{subject} {predicate}: {value}",
                "source_layer": "L2",
                "confidence": item.get("confidence") or item.get("confidence_score"),
                "status": item.get("validation_state") or item.get("status"),
                "occurred_at": item.get("created_at"),
                "updated_at": item.get("updated_at") or item.get("last_validated_at"),
            }
        )
    return findings


def _project_events(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or item.get("summary") or "").strip()
        if not content:
            continue
        findings.append(
            {
                "kind": "event",
                "statement": content,
                "source_layer": "L1",
                "confidence": item.get("score"),
                "status": "active",
                "occurred_at": item.get("timestamp"),
                "updated_at": item.get("timestamp") or item.get("created_at"),
            }
        )
    return findings


def _preserved_l1_event_count(
    *,
    request: RetrievalQuery,
    event_findings: list[dict[str, Any]],
) -> int:
    if not event_findings:
        return 0
    time_range = request.time_range or {}
    has_explicit_time_range = bool(time_range.get("start") is not None or time_range.get("end") is not None)
    if has_explicit_time_range:
        return min(2, max(int(request.limit or 0), 1))
    if is_list_like_query(request.query):
        return 0
    return 1


def _merge_exact_fact_findings(
    event_findings: list[dict[str, Any]],
    derived_findings: list[dict[str, Any]],
    *,
    limit: int,
    preserved_event_count: int,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    merged.extend(event_findings[: min(preserved_event_count, max(limit, 1))])
    remaining = max(limit - len(merged), 0)
    if remaining > 0:
        merged.extend(derived_findings[:remaining])
    return merged


def _project_reflections(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        summary = str(item.get("summary") or item.get("content") or "").strip()
        if not summary:
            continue
        findings.append(
            {
                "kind": "reflection",
                "statement": summary,
                "source_layer": "L3",
                "confidence": item.get("confidence"),
                "status": item.get("status"),
                "occurred_at": item.get("period_start_at"),
                "updated_at": item.get("updated_at") or item.get("created_at"),
            }
        )
    return findings


def _project_procedures(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        description = str(item.get("description") or item.get("summary") or item.get("skill_name") or "").strip()
        if not description:
            continue
        findings.append(
            {
                "kind": "procedure",
                "statement": description,
                "source_layer": "L4",
                "confidence": item.get("success_rate"),
                "status": item.get("status"),
                "occurred_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
            }
        )
    return findings