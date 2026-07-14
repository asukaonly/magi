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
    coverage = historical_recall.get("coverage") or {}
    source_layers = provenance.get("source_layers") or []
    primary_count = provenance.get("primary_count") or 0

    sections: list[str] = []

    # ---- Header ----
    header_parts = [f"status={status}"]
    if mode:
        header_parts.append(f"mode={mode}")
    if source_layers:
        header_parts.append(f"sources={','.join(str(layer) for layer in source_layers)}")
    if primary_count:
        header_parts.append(f"items={primary_count}")
    if coverage:
        header_parts.append(f"coverage={coverage.get('kind') or 'unknown'}")
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

    structured_results = historical_recall.get("structured_results") or []
    if structured_results:
        rendered = _render_structured_results(structured_results, max_items=max_items)
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
    elif bool(coverage.get("can_claim_total")):
        sections.append(
            "Structured coverage is exhaustive only for the stated source and time scope. "
            "Total-count and overall claims are allowed only inside that scope."
        )
    else:
        sections.append(
            "These findings are representative, not exhaustive. "
            "Describe only patterns directly supported by them and frame summaries as "
            "observations from the returned records. Do not infer overall habits, preferences, "
            "diversity, frequency, or totals unless the returned findings directly establish them. "
            "If no clear pattern is supported, report the findings concretely."
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


def _render_structured_results(
    structured_results: list[dict[str, Any]],
    *,
    max_items: int,
) -> str:
    parts: list[str] = []
    for result in structured_results:
        domain = str(result.get("domain") or "memory")
        summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
        lines = [f"## Structured {domain.title()} Result"]
        if domain == "photo":
            if summary:
                lines.append(f"- Sessions: {int(summary.get('session_count') or 0)}")
                lines.append(f"- Total photos: {int(summary.get('photo_count') or 0)}")
                by_year = summary.get("by_year")
                if isinstance(by_year, dict) and by_year:
                    years = ", ".join(f"{year}:{count}" for year, count in by_year.items())
                    lines.append(f"- By year: {years}")
        elif summary:
            event_count = summary.get("event_count")
            metric_label = str(summary.get("metric_label") or "items")
            metric_total = summary.get("metric_total")
            if event_count is not None:
                lines.append(f"- Events: {int(event_count)}")
            if metric_total is not None:
                lines.append(f"- Total {metric_label}: {_format_structured_number(metric_total)}")
            duration_total = summary.get("duration_total_sec")
            if duration_total:
                lines.append(f"- Total duration: {_format_structured_number(duration_total)} sec")
            by_year = summary.get("by_year")
            if isinstance(by_year, dict) and by_year:
                years = ", ".join(f"{year}:{count}" for year, count in by_year.items())
                lines.append(f"- By year: {years}")
        items = result.get("items") if isinstance(result.get("items"), list) else []
        for item in items[:max_items]:
            if not isinstance(item, dict):
                continue
            timestamp = format_timestamp(item.get("timestamp"))
            content = truncate_statement(str(item.get("content") or ""), max_chars=160)[0]
            photo_count = item.get("photo_count")
            metric_value = item.get("metric_value")
            meta = []
            if timestamp:
                meta.append(timestamp)
            if photo_count is not None:
                meta.append(f"{int(photo_count)} photos")
            if domain != "photo" and metric_value is not None:
                metric_label = str(summary.get("metric_label") or "items")
                meta.append(f"{_format_structured_number(metric_value)} {metric_label}")
            suffix = f" ({', '.join(meta)})" if meta else ""
            lines.append(f"- {content}{suffix}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def _format_structured_number(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(numeric)) if numeric.is_integer() else f"{numeric:.2f}".rstrip("0").rstrip(".")


__all__ = ["compact_historical_recall"]
