"""Historical-recall compaction for memory tool context.

Renders HistoricalRecallPayload dict into structured text for LLM consumption,
replacing the previous JSON-dict approach for better token efficiency and
readability.
"""

from __future__ import annotations

from typing import Any

from .recall_rendering import (
    aggregate_by_statement,
    build_asset_manifest,
    format_time_range,
    format_timestamp,
    truncate_statement,
)


def compact_historical_recall(
    historical_recall: dict[str, Any],
    *,
    max_items: int,
    max_text_chars: int,
) -> str:
    """Render historical recall as structured text for LLM consumption."""
    status = str(historical_recall.get("status") or "not_found")
    mode = str(historical_recall.get("query_mode") or "")
    summary = str(historical_recall.get("summary") or "")
    insufficient = bool(historical_recall.get("insufficient_evidence", False))
    provenance = historical_recall.get("provenance") or {}
    source_layers = provenance.get("source_layers") or []
    primary_count = provenance.get("primary_count") or 0

    sections: list[str] = []

    # ---- Header ----
    header_parts = [f"status={status}"]
    if mode:
        header_parts.append(f"mode={mode}")
    if source_layers:
        header_parts.append(f"sources={','.join(str(l) for l in source_layers)}")
    if primary_count:
        header_parts.append(f"total={primary_count}")
    sections.append(f"[Memory Recall] {' | '.join(header_parts)}")

    # ---- Summary ----
    if summary:
        sections.append(f"## Summary\n{summary}")

    # ---- Findings ----
    findings = historical_recall.get("findings") or []
    if findings:
        rendered = _render_findings(findings, max_items=max_items, max_text_chars=max_text_chars)
        if rendered:
            sections.append(rendered)

    # ---- Asset manifest ----
    asset_refs = historical_recall.get("asset_refs") or []
    if asset_refs:
        manifest_text = _render_asset_manifest(asset_refs)
        if manifest_text:
            sections.append(manifest_text)

    # ---- Usage guidance ----
    if status == "not_found" or insufficient:
        sections.append("No confirmed memory found. Do not guess.")
    else:
        sections.append(
            "Source-of-truth for this turn. "
            "Do not guess beyond these findings."
        )

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Internal renderers
# ---------------------------------------------------------------------------

_KIND_LABELS = {
    "relationship": "Knowledge",
    "assertion": "Assertions",
    "event": "Events",
    "reflection": "Reflections",
    "procedure": "Procedures",
}


def _render_findings(
    findings: list[dict[str, Any]],
    *,
    max_items: int,
    max_text_chars: int,
) -> str:
    aggregated = aggregate_by_statement(findings[:max_items])

    by_kind: dict[str, list[dict[str, Any]]] = {}
    for f in aggregated:
        kind = str(f.get("kind") or "event")
        by_kind.setdefault(kind, []).append(f)

    kind_order = ["relationship", "assertion", "reflection", "event", "procedure"]

    parts: list[str] = []
    for kind in kind_order:
        items = by_kind.get(kind)
        if not items:
            continue
        label = _KIND_LABELS.get(kind, kind.title())
        lines: list[str] = [f"## {label}"]
        for item in items:
            line = _render_single_finding(item, max_text_chars=max_text_chars)
            lines.append(line)
        parts.append("\n".join(lines))

    return "\n\n".join(parts)


def _render_single_finding(item: dict[str, Any], *, max_text_chars: int) -> str:
    statement, _ = truncate_statement(
        str(item.get("statement") or ""),
        max_chars=max_text_chars,
    )
    kind = str(item.get("kind") or "")

    meta_parts: list[str] = []

    ts = item.get("occurred_at")
    if ts is not None:
        formatted = format_timestamp(ts)
        if formatted:
            meta_parts.append(formatted)

    count = item.get("count")
    if count is not None and count > 1:
        first_at = item.get("first_at")
        last_at = item.get("last_at")
        range_str = format_time_range(first_at, last_at)
        meta_parts.append(f"×{count}")
        if range_str:
            meta_parts.append(range_str)

    conf = item.get("confidence")
    if conf is not None and kind != "event":
        meta_parts.append(f"conf={conf:.2f}")

    evidence = str(item.get("evidence_text") or "").strip()
    if evidence:
        ev_text, _ = truncate_statement(evidence, max_chars=min(max_text_chars, 120))
        meta_parts.append(f"evidence: {ev_text}")

    meta = f" ({', '.join(meta_parts)})" if meta_parts else ""
    return f"- {statement}{meta}"


def _render_asset_manifest(asset_refs: list[dict[str, Any]]) -> str:
    manifest = build_asset_manifest(asset_refs)
    if not manifest:
        return ""
    lines: list[str] = ["## Referenced Assets"]
    for item in manifest:
        display = item.get("display_name", "")
        source = item.get("source_type", "")
        domain = item.get("domain", "")
        count = item.get("count", 1)
        parts = [display]
        if source:
            parts.append(f"source={source}")
        if domain:
            parts.append(f"domain={domain}")
        if count > 1:
            parts.append(f"×{count}")
        lines.append(f"- {', '.join(parts)}")
    return "\n".join(lines)


__all__ = ["compact_historical_recall"]
