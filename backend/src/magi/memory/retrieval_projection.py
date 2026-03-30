"""Projection helpers that turn raw retrieval payloads into answer-facing contracts."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Iterable

from .hybrid_retrieval.models import HistoricalRecallPayload, RetrievalPayload, RetrievalQuery


_WEATHER_LABELS_ZH = {
    "humid": "潮湿天气",
    "rainy": "雨天",
    "sunny": "晴天",
    "cloudy": "阴天",
    "windy": "刮风天气",
    "stormy": "暴风雨天气",
    "hot": "炎热天气",
    "cold": "寒冷天气",
    "snowy": "下雪天",
}


def project_historical_recall(
    *,
    payload: RetrievalPayload | dict[str, Any],
    request: RetrievalQuery | dict[str, Any],
) -> HistoricalRecallPayload:
    """Project a raw retrieval payload into an answer-facing recall contract."""
    normalized_payload = _coerce_payload(payload)
    normalized_request = _coerce_request(request)

    findings = _build_findings(normalized_payload, normalized_request)
    source_layers = _unique_in_order(item["source_layer"] for item in findings)

    status = _derive_status(findings)
    summary = _build_summary(
        findings=findings,
        recall_intent=normalized_request.recall_intent,
        status=status,
    )
    insufficient_evidence = status == "not_found"

    return HistoricalRecallPayload(
        status=status,
        recall_intent=normalized_request.recall_intent,
        query_mode=normalized_request.query_mode or str(normalized_payload.trace.get("query_mode") or "") or None,
        summary=summary,
        findings=findings,
        insufficient_evidence=insufficient_evidence,
        answering_hints={
            "must_not_guess_when_empty": True,
            "prefer_direct_findings": True,
        },
        provenance={
            "primary_count": int(normalized_payload.trace.get("primary_count") or len(findings)),
            "source_layers": source_layers,
        },
    )


def _coerce_payload(payload: RetrievalPayload | dict[str, Any]) -> RetrievalPayload:
    if isinstance(payload, RetrievalPayload):
        return payload
    if is_dataclass(payload):
        payload = asdict(payload)
    if not isinstance(payload, dict):
        return RetrievalPayload()
    return RetrievalPayload(
        l0_workbench=list(payload.get("l0_workbench") or []),
        l1_events=list(payload.get("l1_events") or []),
        l1_evidence_bundles=list(payload.get("l1_evidence_bundles") or []),
        l1_timeline_summary=list(payload.get("l1_timeline_summary") or []),
        l2_entity_cards=list(payload.get("l2_entity_cards") or []),
        l2_relationships=list(payload.get("l2_relationships") or []),
        l2_assertions=list(payload.get("l2_assertions") or []),
        l3_reflections=list(payload.get("l3_reflections") or []),
        l4_procedures=list(payload.get("l4_procedures") or []),
        trace=dict(payload.get("trace") or {}),
    )


def _coerce_request(request: RetrievalQuery | dict[str, Any]) -> RetrievalQuery:
    if isinstance(request, RetrievalQuery):
        return request
    if not isinstance(request, dict):
        return RetrievalQuery(query="", user_id=None, session_id=None, time_range={})
    return RetrievalQuery(
        query=str(request.get("query") or ""),
        user_id=request.get("user_id"),
        session_id=request.get("session_id"),
        time_range=dict(request.get("time_range") or {}),
        recall_intent=request.get("recall_intent"),
        query_mode=request.get("query_mode"),
        source_filters=list(request.get("source_filters") or []),
        domain_filters=list(request.get("domain_filters") or []),
        limit=int(request.get("limit") or 10),
    )


def _build_findings(payload: RetrievalPayload, request: RetrievalQuery) -> list[dict[str, Any]]:
    recall_intent = str(request.recall_intent or "").strip()
    if recall_intent in {"preference_recall", "relationship_recall"}:
        findings = _project_relationships(payload.l2_relationships)
        if findings:
            return findings
        findings = _project_assertions(payload.l2_assertions)
        if findings:
            return findings
        return _project_events(payload.l1_events)
    if recall_intent == "profile_fact_recall":
        findings = _project_assertions(payload.l2_assertions)
        if findings:
            return findings
        findings = _project_relationships(payload.l2_relationships)
        if findings:
            return findings
        return _project_events(payload.l1_events)
    if recall_intent == "workflow_reuse":
        findings = _project_procedures(payload.l4_procedures)
        if findings:
            return findings
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
        evidence_ref_ids = _collect_ids(item.get("triple_id"), item.get("evidence_event_ids"))
        findings.append(
            {
                "kind": "relationship",
                "statement": f"{subject} {predicate} {object_value}",
                "source_layer": "L2",
                "confidence": item.get("confidence"),
                "status": item.get("status"),
                "occurred_at": item.get("first_observed_at"),
                "updated_at": item.get("updated_at"),
                "evidence_ref_ids": evidence_ref_ids,
            }
        )
    return findings


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
                "evidence_ref_ids": _collect_ids(item.get("assertion_id"), item.get("evidence_events")),
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
                "evidence_ref_ids": _collect_ids(item.get("event_id"), item.get("turn_id")),
            }
        )
    return findings


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
                "evidence_ref_ids": _collect_ids(item.get("summary_id"), item.get("source_event_ids")),
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
                "evidence_ref_ids": _collect_ids(item.get("skill_id")),
            }
        )
    return findings


def _build_summary(*, findings: list[dict[str, Any]], recall_intent: str | None, status: str) -> str:
    if status == "not_found":
        return "未检索到可确认的历史记忆。"

    primary = findings[0] if findings else {}
    if primary.get("kind") == "relationship":
        statement = str(primary.get("statement") or "").strip()
        subject, predicate, object_value = _split_relationship_statement(statement)
        object_label = _humanize_object(object_value)
        if recall_intent == "preference_recall":
            if predicate == "LIKES":
                return f"你喜欢{object_label}。"
            if predicate == "DISLIKES":
                return f"你讨厌{object_label}。"
            if predicate == "INTERESTED_IN":
                return f"你对{object_label}感兴趣。"
            if predicate == "FOLLOWS":
                return f"你关注{object_label}。"
        if subject and predicate and object_value:
            return f"{subject} {predicate} {object_value}"

    statement = str(primary.get("statement") or "").strip()
    return statement or "已检索到相关历史记忆。"


def _derive_status(findings: list[dict[str, Any]]) -> str:
    if not findings:
        return "not_found"
    statuses = {str(item.get("status") or "").strip() for item in findings}
    if "conflicted" in statuses or "contradicted" in statuses:
        return "conflicted"
    return "found"


def _split_relationship_statement(statement: str) -> tuple[str, str, str]:
    parts = statement.split()
    if len(parts) < 3:
        return "", "", ""
    return parts[0], parts[1], " ".join(parts[2:])


def _humanize_object(object_value: str) -> str:
    normalized = str(object_value or "").strip()
    if not normalized:
        return "相关对象"
    if ":" in normalized:
        entity_type, _, raw_value = normalized.partition(":")
        if entity_type == "weather_state":
            slug = raw_value.split("-", 1)[0].strip().lower()
            return _WEATHER_LABELS_ZH.get(slug, raw_value.replace("-", " "))
        return raw_value.replace("-", " ")
    return normalized


def _collect_ids(*values: Any) -> list[str]:
    collected: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            for item in value:
                normalized = str(item).strip()
                if normalized:
                    collected.append(normalized)
            continue
        normalized = str(value).strip()
        if normalized:
            collected.append(normalized)
    return collected


def _unique_in_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered
