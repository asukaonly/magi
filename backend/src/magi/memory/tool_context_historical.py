"""Historical-recall compaction for memory tool context."""

from __future__ import annotations

from typing import Any, Dict

from .tool_context_common import truncate_text


def compact_historical_recall(
    historical_recall: Dict[str, Any],
    *,
    max_items: int,
    max_text_chars: int,
) -> Dict[str, Any]:
    compact: Dict[str, Any] = {
        "status": historical_recall.get("status"),
        "query_mode": historical_recall.get("query_mode"),
        "summary": historical_recall.get("summary"),
        "insufficient_evidence": bool(historical_recall.get("insufficient_evidence", False)),
    }

    findings = historical_recall.get("findings")
    if isinstance(findings, list):
        compact_findings: list[dict[str, Any]] = []
        for item in findings[:max_items]:
            if not isinstance(item, dict):
                continue
            statement, statement_truncated = truncate_text(
                item.get("statement"),
                max_text_chars=max_text_chars,
            )
            evidence_text, evidence_truncated = truncate_text(
                item.get("evidence_text"),
                max_text_chars=max_text_chars,
            )
            finding: dict[str, Any] = {
                "kind": item.get("kind"),
                "statement": statement,
                "statement_truncated": statement_truncated,
                "source_layer": item.get("source_layer"),
                "confidence": item.get("confidence"),
                "status": item.get("status"),
                "occurred_at": item.get("occurred_at"),
            }
            if evidence_text:
                finding["evidence_text"] = evidence_text
                finding["evidence_text_truncated"] = evidence_truncated
            compact_findings.append(finding)
        compact["findings"] = compact_findings

    entity_refs = historical_recall.get("entity_refs")
    if isinstance(entity_refs, list):
        compact_entity_refs: list[dict[str, Any]] = []
        for item in entity_refs[:max_items]:
            if not isinstance(item, dict):
                continue
            compact_entity_refs.append(
                {
                    "entity_id": item.get("entity_id"),
                    "entity_type": item.get("entity_type"),
                    "canonical_name": item.get("canonical_name"),
                    "match_source": item.get("match_source"),
                }
            )
        if compact_entity_refs:
            compact["entity_refs"] = compact_entity_refs

    asset_refs = historical_recall.get("asset_refs")
    if isinstance(asset_refs, list):
        compact_asset_refs: list[dict[str, Any]] = []
        for item in asset_refs[:max_items]:
            if not isinstance(item, dict):
                continue
            compact_item = {
                "asset_ref_id": item.get("asset_ref_id"),
                "kind": item.get("kind"),
                "source_type": item.get("source_type"),
                "source_item_id": item.get("source_item_id"),
                "event_id": item.get("event_id"),
                "original_name": item.get("original_name"),
                "display_name": item.get("display_name"),
                "captured_at": item.get("captured_at"),
                "occurred_at": item.get("occurred_at"),
            }
            attributes = item.get("attributes")
            if isinstance(attributes, dict):
                compact_item["attributes"] = dict(attributes)
            compact_asset_refs.append({key: value for key, value in compact_item.items() if value is not None})
        if compact_asset_refs:
            compact["asset_refs"] = compact_asset_refs

    answering_hints = historical_recall.get("answering_hints")
    if isinstance(answering_hints, dict):
        compact["answering_hints"] = dict(answering_hints)

    provenance = historical_recall.get("provenance")
    if isinstance(provenance, dict):
        compact["provenance"] = {
            "primary_count": provenance.get("primary_count"),
            "source_layers": provenance.get("source_layers"),
        }

    return compact


__all__ = ["compact_historical_recall"]
