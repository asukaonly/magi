"""Projection helpers that turn raw retrieval payloads into answer-facing contracts."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Iterable

from .hybrid_retrieval.models import HistoricalRecallPayload, RetrievalPayload, RetrievalQuery
from .retrieval_projection_findings import build_findings as _build_findings
from .retrieval_projection_refs import (
    build_asset_refs as _build_asset_refs,
    build_entity_refs as _build_entity_refs,
    build_plugin_recall_artifacts as _build_plugin_recall_artifacts,
)
from .retrieval_projection_summary import build_summary as _build_summary, derive_status as _derive_status


def project_historical_recall(
    *,
    payload: RetrievalPayload | dict[str, Any],
    request: RetrievalQuery | dict[str, Any],
    plugin_manager: Any | None = None,
) -> HistoricalRecallPayload:
    """Project a raw retrieval payload into an answer-facing recall contract."""
    normalized_payload = _coerce_payload(payload)
    normalized_request = _coerce_request(request)
    plugin_recall_artifacts = _build_plugin_recall_artifacts(
        payload=normalized_payload,
        query=normalized_request.query,
        query_mode=normalized_request.query_mode,
        plugin_manager=plugin_manager,
    )

    findings = _build_findings(normalized_payload, normalized_request)
    entity_refs = _build_entity_refs(
        normalized_payload,
        plugin_entity_refs=plugin_recall_artifacts.get("entity_refs", []),
    )
    asset_refs = _build_asset_refs(
        normalized_payload,
        query=normalized_request.query,
        query_mode=normalized_request.query_mode,
        plugin_asset_refs=plugin_recall_artifacts.get("asset_refs", []),
    )
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
        entity_refs=entity_refs,
        asset_refs=asset_refs,
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
