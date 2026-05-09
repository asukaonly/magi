"""Finding projection helpers for historical recall payloads.

All memory layers are projected into a unified candidate list, scored by
a quality signal (confidence / retrieval score) plus a soft mode-preference
bonus, then sorted.  This replaces the previous per-mode if-else hard
selection that discarded useful cross-layer evidence.
"""

from __future__ import annotations

from typing import Any

from .hybrid_retrieval.models import RetrievalPayload, RetrievalQuery
from .recall_rendering import is_echo_finding
from .retrieval_projection_summary import split_relationship_statement


# ---------------------------------------------------------------------------
# Mode → kind soft-weight table
# ---------------------------------------------------------------------------

_MODE_KIND_WEIGHTS: dict[str, dict[str, float]] = {
    "exact_fact":       {"relationship": 0.30, "assertion": 0.20, "event": 0.00, "reflection": 0.05, "procedure": 0.00},
    "current_state":    {"assertion": 0.30, "relationship": 0.15, "event": 0.05, "reflection": 0.05, "procedure": 0.00},
    "episode_recall":   {"event": 0.20, "reflection": 0.10, "relationship": 0.05, "assertion": 0.05, "procedure": 0.00},
    "activity_summary": {"reflection": 0.30, "event": 0.15, "relationship": 0.00, "assertion": 0.00, "procedure": 0.00},
    "summary":          {"reflection": 0.30, "event": 0.10, "relationship": 0.05, "assertion": 0.05, "procedure": 0.00},
    "strategy":         {"procedure": 0.30, "reflection": 0.20, "event": 0.05, "relationship": 0.00, "assertion": 0.00},
    "cross_session":    {"event": 0.20, "relationship": 0.10, "reflection": 0.10, "assertion": 0.05, "procedure": 0.00},
    "temporal_compare": {"event": 0.15, "assertion": 0.15, "relationship": 0.10, "reflection": 0.10, "procedure": 0.00},
    "event_stream":     {"event": 0.25, "reflection": 0.05, "relationship": 0.00, "assertion": 0.00, "procedure": 0.00},
}

_CONFIDENCE_FLOOR = 0.35

_PREDICATE_BONUS: dict[str, dict[str, dict[str, float]]] = {
    "positive": {
        "creator":  {"FOLLOWS": 0.25, "LIKES": 0.10, "INTERESTED_IN": 0.05, "DISLIKES": 0.00},
        "place":    {"LIKES": 0.20, "VISITED": 0.15, "DISLIKES": 0.00},
        "topic":    {"INTERESTED_IN": 0.30, "LIKES": 0.10, "DISLIKES": 0.00},
        "software": {"LIKES": 0.20, "USES": 0.15, "DISLIKES": 0.00},
    },
    "negative": {
        "_default": {"DISLIKES": 0.25, "LIKES": 0.05, "INTERESTED_IN": 0.03, "FOLLOWS": 0.00, "USES": 0.00, "VISITED": 0.00},
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_findings(payload: RetrievalPayload, request: RetrievalQuery) -> list[dict[str, Any]]:
    """Build a ranked list of findings from all memory layers.

    Every layer's results are projected, scored with a unified quality
    metric, and sorted.  Mode preference is a soft bonus rather than a
    hard layer selector.
    """
    candidates: list[dict[str, Any]] = []
    candidates.extend(_project_events(payload.l1_events))
    candidates.extend(_project_relationships(payload.l2_relationships))
    candidates.extend(_project_assertions(payload.l2_assertions))
    candidates.extend(_project_reflections(payload.l3_reflections))
    candidates.extend(_project_procedures(payload.l4_procedures))

    mode = str(request.query_mode or "").strip() or "exact_fact"
    answer_kind = _infer_answer_kind(payload=payload, request=request)
    polarity = _infer_query_polarity(request.query)

    for c in candidates:
        _attach_score(c, mode=mode, answer_kind=answer_kind, polarity=polarity)

    candidates = [c for c in candidates if not is_echo_finding(c, request.query)]

    candidates.sort(key=lambda x: -float(x.get("_score", 0.0)))

    limit = max(int(request.limit or 10), 1)
    return candidates[:limit]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _attach_score(
    finding: dict[str, Any],
    *,
    mode: str,
    answer_kind: str,
    polarity: str,
) -> None:
    kind = str(finding.get("kind") or "event")

    raw_confidence = float(finding.get("confidence") or 0.0)
    retrieval_score = float(finding.get("_retrieval_score") or 0.0)

    if kind == "event":
        base = retrieval_score if retrieval_score > 0 else max(raw_confidence, 0.3)
    elif kind == "procedure":
        base = max(raw_confidence, 0.3)
    else:
        base = max(raw_confidence, 0.1)

    if base < _CONFIDENCE_FLOOR:
        base *= 0.5

    mode_bonus = _MODE_KIND_WEIGHTS.get(mode, {}).get(kind, 0.0)

    predicate_bonus = 0.0
    if kind == "relationship":
        statement = str(finding.get("statement") or "")
        _, predicate, _ = split_relationship_statement(statement)
        predicate_upper = predicate.upper()
        if polarity == "negative":
            predicate_bonus = _PREDICATE_BONUS["negative"].get("_default", {}).get(predicate_upper, 0.0)
        else:
            predicate_bonus = _PREDICATE_BONUS["positive"].get(answer_kind, {}).get(predicate_upper, 0.0)

    finding["_score"] = base + mode_bonus + predicate_bonus


# ---------------------------------------------------------------------------
# Per-layer projection helpers
# ---------------------------------------------------------------------------

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
            "_retrieval_score": float(item.get("_fusion_score") or item.get("confidence") or 0.0),
        }
        evidence_text = str(item.get("evidence_text") or "").strip()
        if evidence_text:
            finding["evidence_text"] = evidence_text
        findings.append(finding)
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
                "_retrieval_score": float(item.get("confidence") or item.get("confidence_score") or 0.0),
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
                "_retrieval_score": float(item.get("score") or item.get("retrieval_score") or 0.0),
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
                "_retrieval_score": float(item.get("confidence") or 0.5),
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
                "_retrieval_score": float(item.get("success_rate") or 0.5),
            }
        )
    return findings


# ---------------------------------------------------------------------------
# Inference helpers (preserved from original)
# ---------------------------------------------------------------------------

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
