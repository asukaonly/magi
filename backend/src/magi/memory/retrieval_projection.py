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
        query=normalized_request.query,
        query_mode=normalized_request.query_mode,
        status=status,
    )
    insufficient_evidence = status == "not_found"

    return HistoricalRecallPayload(
        status=status,
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
        l2_episodes=list(payload.get("l2_episodes") or []),
        l2_state_facts=list(payload.get("l2_state_facts") or []),
        l2_state_history=list(payload.get("l2_state_history") or []),
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
        query_mode=request.get("query_mode"),
        source_filters=list(request.get("source_filters") or []),
        domain_filters=list(request.get("domain_filters") or []),
        limit=int(request.get("limit") or 10),
    )


def _build_findings(payload: RetrievalPayload, request: RetrievalQuery) -> list[dict[str, Any]]:
    query_mode = str(request.query_mode or "").strip()

    # Fact-oriented modes: prefer L2 semantic data
    if query_mode in {"exact_fact", "current_state"}:
        findings = _project_relationships(payload.l2_relationships)
        if findings:
            if query_mode == "exact_fact":
                return _sort_preference_relationship_findings(findings, payload=payload, request=request)
            return findings
        findings = _project_assertions(payload.l2_assertions)
        if findings:
            return findings
        return _project_events(payload.l1_events)

    # Strategy mode: prefer L4
    if query_mode == "strategy":
        findings = _project_procedures(payload.l4_procedures)
        if findings:
            return findings
        findings = _project_reflections(payload.l3_reflections)
        if findings:
            return findings
        return _project_events(payload.l1_events)

    # Summary mode: prefer L3
    if query_mode == "summary":
        findings = _project_reflections(payload.l3_reflections)
        if findings:
            return findings
        return _project_events(payload.l1_events)

    # Episode / cross-session / temporal / default: prefer events
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
        finding: dict[str, Any] = {
            "kind": "relationship",
            "statement": f"{subject} {predicate} {object_value}",
            "source_layer": "L2",
            "confidence": item.get("confidence"),
            "status": item.get("status"),
            "occurred_at": item.get("first_observed_at"),
            "updated_at": item.get("updated_at"),
            "evidence_ref_ids": evidence_ref_ids,
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
        _, predicate, _ = _split_relationship_statement(statement)
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


def _build_summary(
    *,
    findings: list[dict[str, Any]],
    query: str,
    query_mode: str | None,
    status: str,
) -> str:
    if status == "not_found":
        return "未检索到可确认的历史记忆。"

    if query_mode == "exact_fact" and _is_list_like_query(query):
        grouped_summary = _build_grouped_preference_summary(findings)
        if grouped_summary:
            return grouped_summary

    primary = findings[0] if findings else {}
    if primary.get("kind") == "relationship":
        statement = str(primary.get("statement") or "").strip()
        subject, predicate, object_value = _split_relationship_statement(statement)
        object_label = _humanize_object(object_value)
        if query_mode == "exact_fact":
            if predicate == "LIKES":
                return f"你喜欢{object_label}。"
            if predicate == "DISLIKES":
                return f"你讨厌{object_label}。"
            if predicate == "INTERESTED_IN":
                return f"你对{object_label}感兴趣。"
            if predicate == "FOLLOWS":
                return f"你关注{object_label}。"
            if predicate == "USES":
                return f"你有使用{object_label}的记录。"
        if subject and predicate and object_value:
            return f"{subject} {predicate} {object_value}"

    statement = str(primary.get("statement") or "").strip()
    return statement or "已检索到相关历史记忆。"


def _build_grouped_preference_summary(findings: list[dict[str, Any]]) -> str | None:
    relationship_findings = [
        item for item in findings
        if str(item.get("kind") or "").strip() == "relationship"
    ]
    if len(relationship_findings) < 2:
        return None

    subject, predicate, object_value = _split_relationship_statement(
        str(relationship_findings[0].get("statement") or "").strip()
    )
    if not subject or not predicate or not object_value:
        return None

    labels: list[str] = []
    for item in relationship_findings:
        item_subject, item_predicate, item_object_value = _split_relationship_statement(
            str(item.get("statement") or "").strip()
        )
        if item_subject != subject or item_predicate != predicate or not item_object_value:
            break
        label = _humanize_object(item_object_value)
        if label and label not in labels:
            labels.append(label)
        if len(labels) >= 3:
            break

    if len(labels) < 2:
        return None

    joined_labels = "、".join(labels)
    if predicate == "LIKES":
        return f"你喜欢{joined_labels}。"
    if predicate == "DISLIKES":
        return f"你讨厌{joined_labels}。"
    if predicate == "INTERESTED_IN":
        return f"你对{joined_labels}感兴趣。"
    if predicate == "FOLLOWS":
        return f"你关注{joined_labels}。"
    if predicate == "USES":
        return f"你有使用{joined_labels}的记录。"
    return None


def _is_list_like_query(query: str) -> bool:
    query_lower = str(query or "").strip().lower()
    return any(token in query_lower for token in ("哪些", "什么", "谁", "哪几个", "which", "what"))


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
        if entity_type == "topic":
            topic_label = raw_value.replace("-", " ").strip()
            return f"{topic_label}题材" if topic_label else "相关题材"
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
