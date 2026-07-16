"""Projection helpers that turn raw retrieval payloads into answer-facing contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Iterable

from .context_scope.models import normalize_context_resolution_signals
from .hybrid_retrieval.models import HistoricalRecallPayload, RetrievalPayload, RetrievalQuery
from .retrieval_projection_findings import build_findings as _build_findings
from .retrieval_projection_refs import (
    build_asset_refs as _build_asset_refs,
    build_entity_refs as _build_entity_refs,
    build_plugin_recall_artifacts as _build_plugin_recall_artifacts,
)
from .retrieval_projection_summary import (
    build_summary as _build_summary,
    derive_status as _derive_status,
)


@dataclass(frozen=True)
class _ProjectionParts:
    findings: list[dict[str, Any]]
    entity_refs: list[dict[str, Any]]
    asset_refs: list[dict[str, Any]]
    structured_results: list[dict[str, Any]]
    source_layers: list[str]


def project_historical_recall(
    *,
    payload: RetrievalPayload | dict[str, Any],
    request: RetrievalQuery | dict[str, Any],
    plugin_projection_service: Any | None = None,
    canonical_names: dict[str, str] | None = None,
) -> HistoricalRecallPayload:
    """Project a raw retrieval payload into an answer-facing recall contract.

    When ``canonical_names`` is supplied, findings whose subject/object
    ``entity_id`` has no entry in the map are DROPPED rather than rendered
    with the raw id. The drop count is recorded in ``payload.trace`` as
    ``dropped_unresolved_entity_count`` (only when greater than zero).

    When ``canonical_names`` is ``None`` (the default), behavior is
    identical to the legacy projection — callers that pre-resolve names
    via the ``subject``/``object`` fields keep working unchanged.
    """
    normalized_payload = _coerce_payload(payload)
    normalized_request = _coerce_request(request)
    parts = _build_projection_parts(
        normalized_payload=normalized_payload,
        normalized_request=normalized_request,
        plugin_projection_service=plugin_projection_service,
        canonical_names=canonical_names,
    )

    status = _projection_status(parts.structured_results, parts.findings)
    summary = _projection_summary(
        structured_results=parts.structured_results,
        findings=parts.findings,
        query=normalized_request.query,
        query_mode=normalized_request.query_mode,
        status=status,
    )
    coverage = _build_coverage(
        structured_results=parts.structured_results,
        finding_count=len(parts.findings),
        status=status,
    )

    return HistoricalRecallPayload(
        status=status,
        query_mode=_projected_query_mode(normalized_payload, normalized_request),
        summary=summary,
        findings=parts.findings,
        entity_refs=parts.entity_refs,
        asset_refs=parts.asset_refs,
        insufficient_evidence=status == "not_found",
        answering_hints=_answering_hints(coverage),
        provenance=_provenance(normalized_payload, parts.findings, parts.source_layers),
        coverage=coverage,
        structured_results=parts.structured_results,
    )


def _build_projection_parts(
    *,
    normalized_payload: RetrievalPayload,
    normalized_request: RetrievalQuery,
    plugin_projection_service: Any | None,
    canonical_names: dict[str, str] | None,
) -> _ProjectionParts:
    plugin_recall_artifacts = _build_plugin_recall_artifacts(
        payload=normalized_payload,
        query=normalized_request.query,
        query_mode=normalized_request.query_mode,
        plugin_projection_service=plugin_projection_service,
    )

    findings, dropped_unresolved = _build_findings(
        normalized_payload, normalized_request, canonical_names
    )
    _record_dropped_unresolved(normalized_payload, dropped_unresolved)
    entity_refs = _build_entity_refs(
        normalized_payload,
        plugin_entity_refs=plugin_recall_artifacts.get("entity_refs", []),
        canonical_names=canonical_names,
    )
    asset_refs = _build_asset_refs(
        normalized_payload,
        query=normalized_request.query,
        query_mode=normalized_request.query_mode,
        plugin_asset_refs=plugin_recall_artifacts.get("asset_refs", []),
    )
    structured_results = list(normalized_payload.structured_results or [])
    source_layers = _unique_in_order(item["source_layer"] for item in findings)

    return _ProjectionParts(
        findings=findings,
        entity_refs=entity_refs,
        asset_refs=asset_refs,
        structured_results=structured_results,
        source_layers=source_layers,
    )


def _record_dropped_unresolved(payload: RetrievalPayload, dropped_count: int) -> None:
    if dropped_count > 0:
        payload.trace["dropped_unresolved_entity_count"] = dropped_count


def _projection_status(
    structured_results: list[dict[str, Any]], findings: list[dict[str, Any]]
) -> str:
    return "found" if structured_results else _derive_status(findings)


def _projection_summary(
    *,
    structured_results: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    query: str,
    query_mode: str | None,
    status: str,
) -> str:
    if structured_results:
        return _build_structured_summary(structured_results[0])
    return _build_summary(
        findings=findings,
        query=query,
        query_mode=query_mode,
        status=status,
    )


def _projected_query_mode(payload: RetrievalPayload, request: RetrievalQuery) -> str | None:
    return request.query_mode or str(payload.trace.get("query_mode") or "") or None


def _answering_hints(coverage: dict[str, Any]) -> dict[str, Any]:
    return {
        "must_not_guess_when_empty": True,
        "prefer_direct_findings": True,
        "can_claim_total": bool(coverage.get("can_claim_total")),
    }


def _provenance(
    payload: RetrievalPayload,
    findings: list[dict[str, Any]],
    source_layers: list[str],
) -> dict[str, Any]:
    return {
        "primary_count": int(payload.trace.get("primary_count") or len(findings)),
        "source_layers": source_layers,
    }


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
        l2_experiences=list(payload.get("l2_experiences") or []),
        l2_state_facts=list(payload.get("l2_state_facts") or []),
        l2_state_history=list(payload.get("l2_state_history") or []),
        structured_results=list(payload.get("structured_results") or []),
        trace=dict(payload.get("trace") or {}),
    )


def _coerce_request(request: RetrievalQuery | dict[str, Any]) -> RetrievalQuery:
    if isinstance(request, RetrievalQuery):
        return request
    if not isinstance(request, dict):
        return RetrievalQuery(query="", user_id=None, session_id=None, time_range={})
    # Round 5 #8: propagate ALL RetrievalQuery fields. The dict path is used
    # by tests + plugin code; silently dropping fields like exclude_user_text
    # (echo filter) or conversation_context (indexical anchor) degrades
    # behavior in ways callers wouldn't expect.
    return RetrievalQuery(
        query=str(request.get("query") or ""),
        user_id=request.get("user_id"),
        session_id=request.get("session_id"),
        time_range=dict(request.get("time_range") or {}),
        query_mode=request.get("query_mode"),
        source_filters=list(request.get("source_filters") or []),
        domain_filters=list(request.get("domain_filters") or []),
        summary_categories=list(request.get("summary_categories") or []),
        context_scope=dict(request.get("context_scope") or {}),
        context_signals=normalize_context_resolution_signals(request.get("context_signals")),
        limit=int(request.get("limit") or 10),
        exclude_user_text=request.get("exclude_user_text"),
        conversation_context=request.get("conversation_context"),
    )


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


def _build_coverage(
    *,
    structured_results: list[dict[str, Any]],
    finding_count: int,
    status: str,
) -> dict[str, Any]:
    if structured_results:
        coverage = dict(structured_results[0].get("coverage") or {})
        coverage.setdefault("kind", "exhaustive")
        coverage.setdefault("can_claim_total", True)
        return coverage
    return {
        "kind": "sample" if status == "found" else "unknown",
        "can_claim_total": False,
        "returned_count": finding_count,
        "source": "generic_recall",
    }


def _build_structured_summary(result: dict[str, Any]) -> str:
    summary = result.get("summary")
    if not isinstance(summary, dict):
        return "Structured memory result found."
    domain = str(result.get("domain") or "memory")
    if domain == "photo":
        session_count = int(summary.get("session_count") or 0)
        photo_count = int(summary.get("photo_count") or 0)
        return (
            "Structured photo recall found " f"{session_count} sessions and {photo_count} photos."
        )
    return "Structured memory result found."
