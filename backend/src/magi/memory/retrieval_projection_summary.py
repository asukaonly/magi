"""Summary and status helpers for historical recall projection."""

from __future__ import annotations

from typing import Any


WEATHER_LABELS_ZH = {
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


def build_summary(
    *,
    findings: list[dict[str, Any]],
    query: str,
    query_mode: str | None,
    status: str,
) -> str:
    if status == "not_found":
        return "未检索到可确认的历史记忆。"

    if is_list_like_query(query):
        grouped_summary = _build_grouped_preference_summary(findings)
        if grouped_summary:
            return grouped_summary

    relationship_findings = [f for f in findings if f.get("kind") == "relationship"]
    if relationship_findings:
        primary = relationship_findings[0]
        statement = str(primary.get("statement") or "").strip()
        subject, predicate, object_value = split_relationship_statement(statement)
        object_label = humanize_object(object_value)
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

    assertion_findings = [f for f in findings if f.get("kind") == "assertion"]
    if assertion_findings:
        return str(assertion_findings[0].get("statement") or "").strip() or "已检索到相关历史记忆。"

    reflection_findings = [f for f in findings if f.get("kind") == "reflection"]
    if reflection_findings:
        return str(reflection_findings[0].get("statement") or "").strip() or "已检索到相关历史记忆。"

    primary = findings[0] if findings else {}
    statement = str(primary.get("statement") or "").strip()
    if statement and primary.get("evidence_semantics") == "historical_record":
        return f"当时记录：{statement}"
    return statement or f"关于「{query}」的历史记忆。" if findings else "已检索到相关历史记忆。"


def derive_status(findings: list[dict[str, Any]]) -> str:
    if not findings:
        return "not_found"
    statuses = {str(item.get("status") or "").strip() for item in findings}
    if "conflicted" in statuses or "contradicted" in statuses:
        return "conflicted"
    return "found"


def is_list_like_query(query: str) -> bool:
    query_lower = str(query or "").strip().lower()
    return any(token in query_lower for token in ("哪些", "什么", "谁", "哪几个", "which", "what"))


def split_relationship_statement(statement: str) -> tuple[str, str, str]:
    parts = statement.split()
    if len(parts) < 3:
        return "", "", ""
    return parts[0], parts[1], " ".join(parts[2:])


def humanize_object(object_value: str) -> str:
    normalized = str(object_value or "").strip()
    if not normalized:
        return "相关对象"
    if ":" in normalized:
        entity_type, _, raw_value = normalized.partition(":")
        if entity_type == "weather_state":
            slug = raw_value.split("-", 1)[0].strip().lower()
            return WEATHER_LABELS_ZH.get(slug, raw_value.replace("-", " "))
        if entity_type == "topic":
            topic_label = raw_value.replace("-", " ").strip()
            return f"{topic_label}题材" if topic_label else "相关题材"
        return raw_value.replace("-", " ")
    return normalized


def _build_grouped_preference_summary(findings: list[dict[str, Any]]) -> str | None:
    relationship_findings = [
        item for item in findings
        if str(item.get("kind") or "").strip() == "relationship"
    ]
    if len(relationship_findings) < 2:
        return None

    subject, predicate, object_value = split_relationship_statement(
        str(relationship_findings[0].get("statement") or "").strip()
    )
    if not subject or not predicate or not object_value:
        return None

    labels: list[str] = []
    for item in relationship_findings:
        item_subject, item_predicate, item_object_value = split_relationship_statement(
            str(item.get("statement") or "").strip()
        )
        if item_subject != subject or item_predicate != predicate or not item_object_value:
            break
        label = humanize_object(item_object_value)
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
