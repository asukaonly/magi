"""Finding projection helpers for historical recall payloads.

All memory layers are projected into a unified candidate list, scored by
a quality signal (confidence / retrieval score) plus a soft mode-preference
bonus, then sorted.  This replaces the previous per-mode if-else hard
selection that discarded useful cross-layer evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .entity_display import display_name_for
from .hybrid_retrieval.mode_registry import MODE_REGISTRY
from .hybrid_retrieval.models import RetrievalPayload, RetrievalQuery
from .recall_rendering import is_echo_finding
from .retrieval_projection_summary import split_relationship_statement

# Fallback per-layer quota when a mode declares none (defensive; all registry
# modes set layer_quota in T1).
_DEFAULT_LAYER_QUOTA: dict[str, int] = {"L1": 8, "L2": 6, "L3": 3, "L4": 2}
# Floor so a layer that has candidates is never fully starved by a small quota.
_LAYER_QUOTA_FLOOR = 1
_HISTORICAL_EVENT_MODES = frozenset(
    {"event_stream", "episode_recall", "experience_recall"}
)


def _resolve_layer_quota(mode: str) -> dict[str, int]:
    plan = MODE_REGISTRY.get(mode)
    if plan is not None and plan.layer_quota:
        return dict(plan.layer_quota)
    return dict(_DEFAULT_LAYER_QUOTA)


# ---------------------------------------------------------------------------
# Mode → kind soft-weight table
# ---------------------------------------------------------------------------

_MODE_KIND_WEIGHTS: dict[str, dict[str, float]] = {
    "exact_fact": {
        "relationship": 0.30,
        "assertion": 0.20,
        "experience": 0.00,
        "event": 0.00,
        "reflection": 0.05,
        "procedure": 0.00,
    },
    "current_state": {
        "assertion": 0.30,
        "relationship": 0.15,
        "experience": 0.00,
        "event": 0.05,
        "reflection": 0.05,
        "procedure": 0.00,
    },
    "episode_recall": {
        "experience": 0.18,
        "event": 0.20,
        "reflection": 0.10,
        "relationship": 0.05,
        "assertion": 0.05,
        "procedure": 0.00,
    },
    "experience_recall": {
        "experience": 0.35,
        "event": 0.15,
        "reflection": 0.10,
        "relationship": 0.05,
        "assertion": 0.05,
        "procedure": 0.00,
    },
    "activity_summary": {
        "reflection": 0.30,
        "experience": 0.05,
        "event": 0.15,
        "relationship": 0.00,
        "assertion": 0.00,
        "procedure": 0.00,
    },
    "summary": {
        "reflection": 0.30,
        "experience": 0.10,
        "event": 0.10,
        "relationship": 0.05,
        "assertion": 0.05,
        "procedure": 0.00,
    },
    "strategy": {
        "procedure": 0.30,
        "reflection": 0.20,
        "experience": 0.00,
        "event": 0.05,
        "relationship": 0.00,
        "assertion": 0.00,
    },
    "cross_session": {
        "event": 0.20,
        "experience": 0.10,
        "relationship": 0.10,
        "reflection": 0.10,
        "assertion": 0.05,
        "procedure": 0.00,
    },
    "temporal_compare": {
        "event": 0.15,
        "assertion": 0.15,
        "relationship": 0.10,
        "experience": 0.10,
        "reflection": 0.10,
        "procedure": 0.00,
    },
    "event_stream": {
        "event": 0.25,
        "experience": 0.00,
        "reflection": 0.05,
        "relationship": 0.00,
        "assertion": 0.00,
        "procedure": 0.00,
    },
}

_CONFIDENCE_FLOOR = 0.35

_PREDICATE_BONUS: dict[str, dict[str, dict[str, float]]] = {
    "positive": {
        "creator": {"FOLLOWS": 0.25, "LIKES": 0.10, "INTERESTED_IN": 0.05, "DISLIKES": 0.00},
        "place": {"LIKES": 0.20, "VISITED": 0.15, "DISLIKES": 0.00},
        "topic": {"INTERESTED_IN": 0.30, "LIKES": 0.10, "DISLIKES": 0.00},
        "software": {"LIKES": 0.20, "USES": 0.15, "DISLIKES": 0.00},
    },
    "negative": {
        "_default": {
            "DISLIKES": 0.25,
            "LIKES": 0.05,
            "INTERESTED_IN": 0.03,
            "FOLLOWS": 0.00,
            "USES": 0.00,
            "VISITED": 0.00,
        },
    },
}


@dataclass(slots=True)
class _ProjectedFindings:
    candidates: list[dict[str, Any]]
    projection_dropped: list[dict[str, Any]]
    relationship_dropped: int
    assertion_dropped: int

    @property
    def dropped_count(self) -> int:
        return self.relationship_dropped + self.assertion_dropped


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_findings(
    payload: RetrievalPayload,
    request: RetrievalQuery,
    canonical_names: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Build a ranked list of findings from all memory layers.

    Every layer's results are projected, scored with a unified quality
    metric, and sorted.  Mode preference is a soft bonus rather than a
    hard layer selector.

    Returns ``(findings, dropped_count)``. ``dropped_count > 0`` when
    ``canonical_names`` is supplied and some L2 findings were filtered
    because their referenced entity_ids had no canonical name (would
    otherwise leak raw hashes into the user-facing envelope).
    """
    mode = str(request.query_mode or "").strip() or "exact_fact"
    projected = _project_payload_findings(
        payload=payload,
        request=request,
        mode=mode,
        canonical_names=canonical_names,
    )
    _score_projected_findings(projected.candidates, payload=payload, request=request, mode=mode)
    candidates = _drop_echo_findings(projected.candidates, request=request)
    selected, quota_trace = _select_findings_by_layer_quota(candidates, mode=mode)
    _attach_finding_topics(selected)
    _record_projection_trace(
        payload=payload,
        projection_dropped=projected.projection_dropped,
        mode=mode,
        quota_trace=quota_trace,
    )
    return selected, projected.dropped_count


def _project_payload_findings(
    *,
    payload: RetrievalPayload,
    request: RetrievalQuery,
    mode: str,
    canonical_names: dict[str, str] | None,
) -> _ProjectedFindings:
    projection_dropped: list[dict[str, Any]] = []
    candidates = _project_events(
        payload.l1_events,
        mode=mode,
        explicit_chat_source=_has_explicit_chat_source(request.source_filters),
        dropped_sink=projection_dropped,
    )
    rel_findings, rel_dropped = _project_relationships(payload.l2_relationships, canonical_names)
    asrt_findings, asrt_dropped = _project_assertions(payload.l2_assertions, canonical_names)
    candidates.extend(rel_findings)
    candidates.extend(asrt_findings)
    candidates.extend(_project_experiences(payload.l2_experiences))
    candidates.extend(_project_reflections(payload.l3_reflections))
    candidates.extend(_project_procedures(payload.l4_procedures))
    return _ProjectedFindings(
        candidates=candidates,
        projection_dropped=projection_dropped,
        relationship_dropped=rel_dropped,
        assertion_dropped=asrt_dropped,
    )


def _score_projected_findings(
    candidates: list[dict[str, Any]],
    *,
    payload: RetrievalPayload,
    request: RetrievalQuery,
    mode: str,
) -> None:
    answer_kind = _infer_answer_kind(payload=payload, request=request)
    polarity = _infer_query_polarity(request.query)
    for candidate in candidates:
        _attach_score(candidate, mode=mode, answer_kind=answer_kind, polarity=polarity)


def _drop_echo_findings(
    candidates: list[dict[str, Any]],
    *,
    request: RetrievalQuery,
) -> list[dict[str, Any]]:
    echo_texts = [request.query]
    if request.exclude_user_text:
        echo_texts.append(request.exclude_user_text)
    return [
        candidate
        for candidate in candidates
        if not any(is_echo_finding(candidate, text) for text in echo_texts if text)
    ]


def _select_findings_by_layer_quota(
    candidates: list[dict[str, Any]],
    *,
    mode: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    quota = _resolve_layer_quota(mode)
    by_layer: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        by_layer.setdefault(str(candidate.get("source_layer") or "L1"), []).append(candidate)

    selected: list[dict[str, Any]] = []
    quota_trace: dict[str, int] = {}
    for layer, items in by_layer.items():
        items.sort(key=lambda x: float(x.get("_score", 0.0)), reverse=True)
        kept = items[: max(_LAYER_QUOTA_FLOOR, int(quota.get(layer, 0)))]
        selected.extend(kept)
        quota_trace[layer] = len(kept)
    return selected, quota_trace


def _attach_finding_topics(findings: list[dict[str, Any]]) -> None:
    for finding in findings:
        finding["topic"] = _derive_finding_topic(finding)


def _record_projection_trace(
    *,
    payload: RetrievalPayload,
    projection_dropped: list[dict[str, Any]],
    mode: str,
    quota_trace: dict[str, int],
) -> None:
    if projection_dropped:
        payload.trace["projection_filter"] = {
            "dropped": projection_dropped,
            "count": len(projection_dropped),
        }
    payload.trace["layer_quota"] = {"mode": mode, "kept_per_layer": quota_trace}


# ---------------------------------------------------------------------------
# Human-readable topic synthesis
# ---------------------------------------------------------------------------

_TOPIC_MAX_CHARS = 14
_TOPIC_TRAILING_ELLIPSIS = "…"


def _derive_finding_topic(finding: dict[str, Any]) -> str:
    """Return a short, UI-friendly label that names what was recalled.

    The chat shell renders this on the assistant bubble's "called memories"
    row. We optimize for *the most concrete object* of each finding rather
    than just truncating the long-form statement, so users can scan the row
    and recognize the topic at a glance ("哈基米", "锤子手机情怀") instead
    of seeing the raw subject-predicate-object form.
    """
    kind = str(finding.get("kind") or "").strip()
    if kind == "relationship":
        candidate = _extract_relationship_topic(finding)
    elif kind == "assertion":
        candidate = _extract_assertion_topic(finding)
    elif kind == "experience":
        candidate = _extract_experience_topic(finding)
    elif kind == "procedure":
        candidate = _extract_procedure_topic(finding)
    else:
        candidate = str(finding.get("statement") or "").strip()
    return _truncate_topic(candidate)


def _extract_relationship_topic(finding: dict[str, Any]) -> str:
    statement = str(finding.get("statement") or "").strip()
    if not statement:
        return ""
    subject, _predicate, obj = split_relationship_statement(statement)
    # Strip the optional "type:" prefix injected by L2 entity ids
    # (e.g. "topic:hachi-mi" → "hachi-mi") so users see plain labels.
    obj_label = obj.split(":", 1)[1] if ":" in obj else obj
    if obj_label.strip():
        return obj_label.strip()
    if subject.strip():
        return subject.strip()
    return statement


def _extract_assertion_topic(finding: dict[str, Any]) -> str:
    statement = str(finding.get("statement") or "").strip()
    if not statement:
        return ""
    # Assertions are formatted as "subject predicate: value"; keep the value
    # on the right of the last colon since it's the concrete answer.
    if ": " in statement:
        return statement.rsplit(": ", 1)[1].strip() or statement
    return statement


def _extract_experience_topic(finding: dict[str, Any]) -> str:
    return str(finding.get("title") or finding.get("statement") or "").strip()


def _extract_procedure_topic(finding: dict[str, Any]) -> str:
    statement = str(finding.get("statement") or "").strip()
    return statement


def _truncate_topic(text: str) -> str:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return ""
    if len(normalized) <= _TOPIC_MAX_CHARS:
        return normalized
    return normalized[: _TOPIC_MAX_CHARS - 1].rstrip() + _TOPIC_TRAILING_ELLIPSIS


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
    elif kind == "experience":
        base = retrieval_score if retrieval_score > 0 else max(raw_confidence, 0.5)
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
            predicate_bonus = (
                _PREDICATE_BONUS["negative"].get("_default", {}).get(predicate_upper, 0.0)
            )
        else:
            predicate_bonus = (
                _PREDICATE_BONUS["positive"].get(answer_kind, {}).get(predicate_upper, 0.0)
            )

    finding["_score"] = base + mode_bonus + predicate_bonus


# ---------------------------------------------------------------------------
# Per-layer projection helpers
# ---------------------------------------------------------------------------


def _feedback_ref(
    kind: str,
    item: dict[str, Any],
    *identity_fields: str,
) -> str | None:
    """Return an opaque, stable identity for turn-local recall feedback."""

    for field_name in identity_fields:
        identity = str(item.get(field_name) or "").strip()
        if identity:
            return f"{kind}:{identity}"
    return None


def _project_relationships(
    items: list[dict[str, Any]],
    canonical_names: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Project L2 relationships into findings.

    Returns ``(findings, dropped_count)``.

    When ``canonical_names`` is provided, subject/object are resolved via
    :func:`magi.memory.entity_display.display_name_for` — catalog name wins;
    else the slug part of ``type:slug``; else ``(未命名 {type})`` for
    hash-like slugs; else dropped when the id is not even a ``type:slug``.
    A pre-resolved ``subject``/``object`` string on the item is used as a
    last-resort fallback when the id resolution returns None.

    When ``canonical_names`` is None, behavior matches the legacy fallback
    chain (``subject`` then ``subject_id``) for backward compatibility.
    """
    findings: list[dict[str, Any]] = []
    dropped = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        subject_id = str(item.get("subject_id") or "").strip()
        object_id = str(item.get("object_id") or "").strip()
        pre_subject = str(item.get("subject") or "").strip()
        pre_object = str(item.get("object") or "").strip()

        if canonical_names is not None:
            # Round 4: try catalog → slug → '(未命名 {type})' → fall through
            # to pre-resolved upstream value → drop.
            resolved_subject = display_name_for(subject_id, canonical_names) if subject_id else None
            resolved_object = display_name_for(object_id, canonical_names) if object_id else None
            subject = (resolved_subject or pre_subject).strip()
            object_value = (resolved_object or pre_object).strip()
            if not subject or not object_value:
                dropped += 1
                continue
        else:
            subject = (pre_subject or subject_id).strip()
            object_value = (pre_object or object_id).strip()

        predicate = str(item.get("predicate") or "").strip()
        if not subject or not predicate or not object_value:
            if canonical_names is not None:
                dropped += 1
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
        feedback_ref = _feedback_ref("relationship", item, "triple_id", "id")
        if feedback_ref is not None:
            finding["feedback_ref"] = feedback_ref
        evidence_text = str(item.get("evidence_text") or "").strip()
        if evidence_text:
            finding["evidence_text"] = evidence_text
        findings.append(finding)
    return findings, dropped


def _project_assertions(
    items: list[dict[str, Any]],
    canonical_names: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Project L2 assertions into findings.

    Returns ``(findings, dropped_count)``.

    When ``canonical_names`` is provided, subject and ``target_entity_id``
    are resolved via :func:`magi.memory.entity_display.display_name_for`
    (catalog → slug → ``(未命名 {type})`` → None). Assertions are only
    dropped when the resolver returns None AND no upstream pre-resolved
    field exists.

    When ``canonical_names`` is None, behavior matches the legacy fallback
    chain (``subject`` then ``entity_id``) for backward compatibility.
    """
    findings: list[dict[str, Any]] = []
    dropped = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        subject = _assertion_subject(item, canonical_names)
        if canonical_names is not None and not subject:
            dropped += 1
            continue

        predicate = _assertion_predicate(item)
        value, should_drop = _assertion_value(item, canonical_names)
        if should_drop:
            dropped += 1
            continue
        if not subject or not predicate or not value:
            if canonical_names is not None:
                dropped += 1
            continue
        findings.append(_assertion_finding(item, subject=subject, predicate=predicate, value=value))
    return findings, dropped


def _assertion_subject(
    item: dict[str, Any],
    canonical_names: dict[str, str] | None,
) -> str:
    entity_id = str(item.get("entity_id") or "").strip()
    pre_subject = str(item.get("subject") or "").strip()
    if canonical_names is None:
        return (pre_subject or entity_id).strip()
    resolved_subject = display_name_for(entity_id, canonical_names) if entity_id else None
    return (resolved_subject or pre_subject).strip()


def _assertion_predicate(item: dict[str, Any]) -> str:
    return str(
        item.get("predicate") or item.get("trait_name") or item.get("trait_family") or ""
    ).strip()


def _assertion_value(
    item: dict[str, Any],
    canonical_names: dict[str, str] | None,
) -> tuple[str, bool]:
    direct_value = (
        str(item.get("claim") or "").strip()
        or str(item.get("content") or "").strip()
        or str(item.get("trait_value") or "").strip()
    )
    if direct_value:
        return direct_value, False

    target_id = str(item.get("target_entity_id") or "").strip()
    if not target_id:
        return "", False
    if canonical_names is None:
        return target_id, False

    resolved_target = display_name_for(target_id, canonical_names)
    if not resolved_target:
        return "", True
    return resolved_target, False


def _assertion_finding(
    item: dict[str, Any],
    *,
    subject: str,
    predicate: str,
    value: str,
) -> dict[str, Any]:
    finding = {
        "kind": "assertion",
        "statement": f"{subject} {predicate}: {value}",
        "source_layer": "L2",
        "confidence": item.get("confidence") or item.get("confidence_score"),
        "status": item.get("validation_state") or item.get("status"),
        "occurred_at": item.get("created_at"),
        "updated_at": item.get("updated_at") or item.get("last_validated_at"),
        "_retrieval_score": float(item.get("confidence") or item.get("confidence_score") or 0.0),
    }
    feedback_ref = _feedback_ref("assertion", item, "assertion_id", "id")
    if feedback_ref is not None:
        finding["feedback_ref"] = feedback_ref
    return finding


def _project_experiences(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("user_label") or item.get("title") or "").strip()
        interpretation = str(item.get("magi_interpretation") or item.get("user_note") or "").strip()
        if title and interpretation:
            statement = f"{title}：{interpretation}"
        else:
            statement = title or interpretation
        if not statement:
            continue
        finding = {
            "kind": "experience",
            "statement": statement,
            "title": title,
            "source_layer": "L2",
            "confidence": item.get("narrative_score") or 0.7,
            "status": item.get("status") or "active",
            "occurred_at": item.get("time_start"),
            "updated_at": item.get("updated_at") or item.get("time_end"),
            "source_episode_ids": list(item.get("source_episode_ids") or []),
            "source_event_ids": list(item.get("source_event_ids") or []),
            "_retrieval_score": float(
                item.get("_retrieval_score") or item.get("narrative_score") or 0.0
            ),
        }
        feedback_ref = _feedback_ref("experience", item, "experience_id", "id")
        if feedback_ref is not None:
            finding["feedback_ref"] = feedback_ref
        findings.append(finding)
    return findings


_FACT_LIKE_QUERY_MODES = frozenset(
    {
        "exact_fact",
        "current_state",
        "activity_summary",
        "summary",
        "temporal_compare",
        "strategy",
    }
)

_CHAT_PROJECTION_SOURCES = frozenset(
    {
        "assistant",
        "chat_projector",
        "runtime_event_emitter",
    }
)

_CHAT_SOURCE_FILTERS = frozenset({"chat", "chat_projector"})

# Evidence classes whose events are conversational artifacts rather than
# durable factual evidence. The L1 evidence governance contract already pins
# their ``l1_retrieval_scope`` to ``conversation_only``, so they would not
# reach this projection in fact-like modes; this set is the explicit answer
# to "which evidence classes must we drop if they slip through". Keep this
# in sync with ``backend/src/magi/memory/evidence/policy.py``.
_CONVERSATIONAL_EVIDENCE_CLASSES = frozenset(
    {
        "assistant_freeform",
        "assistant_runtime_derivation",
        "user_question",
        "user_request",
    }
)

# Evidence classes treated as factual evidence even in chat sources. Listed
# explicitly so that adding a new class fails loud here instead of silently
# falling through the conversational filter.
_FACTUAL_EVIDENCE_CLASSES = frozenset(
    {
        "user_self_report",
        "assistant_tool_grounded",
        "external_observation",
    }
)

# Evidence classes that are conservatively treated as non-factual (filtered)
# whenever they slip into a fact-like projection. ``assistant_quote`` is a
# verbatim restatement; ``system_runtime`` is runtime telemetry; both are
# never new factual evidence for the user profile.
_NON_FACTUAL_EVIDENCE_CLASSES = frozenset(
    {
        "assistant_quote",
        "system_runtime",
    }
)

_CHINESE_QUESTION_MARKERS = (
    "什么时候",
    "什么时间",
    "几点",
    "哪天",
    "哪次",
    "哪里",
    "在哪",
    "哪个",
    "哪些",
    "是谁",
    "谁",
    "什么",
    "多少",
    "几次",
    "多久",
    "有没有",
    "是不是",
    "吗",
)

_ENGLISH_QUESTION_MARKERS = (
    "what ",
    "when ",
    "where ",
    "which ",
    "who ",
    "how often",
    "how many",
    "do i ",
    "did i ",
    "have i ",
    "am i ",
    "was i ",
    "remember ",
    "recall ",
)


def _project_events(
    items: list[dict[str, Any]],
    *,
    mode: str = "exact_fact",
    explicit_chat_source: bool = False,
    dropped_sink: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or item.get("summary") or "").strip()
        if not content:
            continue
        if _is_answer_facing_chat_artifact(
            item,
            content=content,
            mode=mode,
            explicit_chat_source=explicit_chat_source,
        ):
            if dropped_sink is not None:
                dropped_sink.append(
                    {
                        "event_id": item.get("event_id"),
                        "evidence_class": _normalized(item.get("evidence_class")) or "unknown",
                        "reason": "answer_facing_chat_artifact",
                    }
                )
            continue
        finding = {
            "kind": "event",
            "statement": content,
            "source_layer": "L1",
            "confidence": item.get("score"),
            "status": "active",
            "occurred_at": item.get("timestamp"),
            "updated_at": item.get("timestamp") or item.get("created_at"),
            "_retrieval_score": float(item.get("score") or item.get("retrieval_score") or 0.0),
        }
        evidence_semantics = str(item.get("evidence_semantics") or "").strip()
        if evidence_semantics:
            finding["evidence_semantics"] = evidence_semantics
        elif mode in _HISTORICAL_EVENT_MODES:
            finding["evidence_semantics"] = "historical_record"
        correction_status = str(item.get("correction_status") or "").strip()
        if correction_status:
            finding["correction_status"] = correction_status
        feedback_ref = _feedback_ref("event", item, "event_id", "id")
        if feedback_ref is not None:
            finding["feedback_ref"] = feedback_ref
        findings.append(finding)
    return findings


def _is_answer_facing_chat_artifact(
    item: dict[str, Any],
    *,
    content: str,
    mode: str,
    explicit_chat_source: bool,
) -> bool:
    """Return True for chat artifacts that are not factual recall evidence.

    Source of truth is the ``evidence_class`` column written by L1 evidence
    governance: when present and recognized, it is trusted verbatim and no
    string heuristic runs. The legacy author/source/content-string heuristic
    is kept strictly as a fallback for rows whose ``evidence_class`` is
    missing or ``unknown`` (older data not yet swept by the L1 evidence
    backfill, or events ingested through a path that bypasses the classifier).
    """
    if explicit_chat_source:
        return False

    # Explicit governance annotation is authoritative in EVERY mode. A row
    # marked user_question / user_request / assistant_freeform is never
    # factual recall evidence, regardless of how the query was routed.
    evidence_class = _normalized(item.get("evidence_class"))
    if evidence_class and evidence_class != "unknown":
        if evidence_class in _CONVERSATIONAL_EVIDENCE_CLASSES:
            return True
        if evidence_class in _NON_FACTUAL_EVIDENCE_CLASSES:
            return True
        return False

    # Fallback heuristic for un-annotated (missing/unknown) rows stays
    # conservative: only fire in fact-like modes, where chat noise is most
    # harmful and a false positive is least costly.
    if mode not in _FACT_LIKE_QUERY_MODES:
        return False

    author_type = _normalized(item.get("author_type"))
    source = _normalized(item.get("source"))
    event_type = _normalized(item.get("event_type"))
    content_type = _normalized(item.get("content_type"))

    if author_type == "assistant" and content_type != "tool_result":
        return event_type == "airesponse" or source in _CHAT_PROJECTION_SOURCES

    if author_type == "user" and source in _CHAT_PROJECTION_SOURCES:
        return _looks_like_question(content)

    return False


def _has_explicit_chat_source(source_filters: list[str]) -> bool:
    return any(_normalized(value) in _CHAT_SOURCE_FILTERS for value in source_filters or [])


def _looks_like_question(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    if "?" in normalized or "？" in normalized:
        return True
    lowered = normalized.lower()
    return any(marker in normalized for marker in _CHINESE_QUESTION_MARKERS) or any(
        marker in lowered for marker in _ENGLISH_QUESTION_MARKERS
    )


def _normalized(value: Any) -> str:
    return str(value or "").strip().lower()


def _project_reflections(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        summary = str(item.get("summary") or item.get("content") or "").strip()
        if not summary:
            continue
        finding = {
            "kind": "reflection",
            "statement": summary,
            "source_layer": "L3",
            "confidence": item.get("confidence"),
            "status": item.get("status"),
            "occurred_at": item.get("period_start_at"),
            "updated_at": item.get("updated_at") or item.get("created_at"),
            "_retrieval_score": float(item.get("confidence") or 0.5),
        }
        feedback_ref = _feedback_ref(
            "reflection",
            item,
            "reflection_id",
            "summary_id",
            "insight_id",
            "id",
        )
        if feedback_ref is not None:
            finding["feedback_ref"] = feedback_ref
        findings.append(finding)
    return findings


def _project_procedures(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        description = str(
            item.get("description") or item.get("summary") or item.get("skill_name") or ""
        ).strip()
        if not description:
            continue
        finding = {
            "kind": "procedure",
            "statement": description,
            "source_layer": "L4",
            "confidence": item.get("success_rate"),
            "status": item.get("status"),
            "occurred_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
            "_retrieval_score": float(item.get("success_rate") or 0.5),
        }
        feedback_ref = _feedback_ref(
            "procedure",
            item,
            "skill_id",
            "procedure_id",
            "experience_id",
            "id",
        )
        if feedback_ref is not None:
            finding["feedback_ref"] = feedback_ref
        findings.append(finding)
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
