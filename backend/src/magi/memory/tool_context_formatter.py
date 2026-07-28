"""Context-formatting helpers for memory tool results."""

from __future__ import annotations

from typing import Any, Dict

from .tool_context_historical import compact_historical_recall as _compact_historical_recall
from .tool_context_layers import (
    compact_assertions as _compact_assertions,
    compact_entity_cards as _compact_entity_cards,
    compact_evidence_bundles as _compact_evidence_bundles,
    compact_experiences as _compact_experiences,
    compact_l1_events as _compact_l1_events,
    compact_procedures as _compact_procedures,
    compact_reflections as _compact_reflections,
    compact_relationships as _compact_relationships,
    compact_timeline_summary as _compact_timeline_summary,
    compact_workbench_items as _compact_workbench_items,
)
from .tool_context_rendering import compact_trace_meta as _compact_trace_meta
from .tool_context_rendering import render_memory_context as _render_memory_context


def compact_memory_tool_data(
    data: Dict[str, Any],
    *,
    max_items: int,
    max_text_chars: int,
) -> Dict[str, Any]:
    """Compress memory_query tool results for LLM tool-message context."""
    if not isinstance(data, dict):
        return data

    historical_recall = data.get("historical_recall")
    if isinstance(historical_recall, dict):
        rendered = _compact_historical_recall(
            historical_recall,
            max_items=max_items,
            max_text_chars=max_text_chars,
        )
        return {"historical_recall": rendered}

    results = data.get("results")
    if not isinstance(results, dict):
        return data

    compact_results = _compact_memory_results(
        results,
        max_items=max_items,
        max_text_chars=max_text_chars,
    )
    compact_meta = _compact_trace_meta(_merged_trace(results, data))
    compact_payload: Dict[str, Any] = {
        "memory_context": _render_memory_context(compact_results),
        "meta": compact_meta,
    }
    if "agent_id" in data:
        compact_payload["agent_id"] = data.get("agent_id")
    return compact_payload


def _compact_memory_results(
    results: Dict[str, Any],
    *,
    max_items: int,
    max_text_chars: int,
) -> Dict[str, Any]:
    compact_results: Dict[str, Any] = {}

    if "l0_workbench" in results:
        compact_results["l0_workbench"] = _compact_workbench_items(
            results.get("l0_workbench"), max_items=max_items, max_text_chars=max_text_chars
        )
    if "l1_events" in results:
        compact_results["l1_events"] = _compact_l1_events(
            results.get("l1_events"), max_items=max_items, max_text_chars=max_text_chars
        )
    if "l1_timeline_summary" in results:
        compact_results["l1_timeline_summary"] = _compact_timeline_summary(
            results.get("l1_timeline_summary"), max_items=max_items, max_text_chars=max_text_chars
        )
    if "l1_evidence_bundles" in results:
        compact_results["l1_evidence_bundles"] = _compact_evidence_bundles(
            results.get("l1_evidence_bundles"), max_items=max_items
        )
    if "l2_entity_cards" in results:
        compact_results["l2_entity_cards"] = _compact_entity_cards(
            results.get("l2_entity_cards"), max_items=max_items, max_text_chars=max_text_chars
        )
    if "l2_relationships" in results:
        compact_results["l2_relationships"] = _compact_relationships(
            results.get("l2_relationships"), max_items=max_items
        )
    if "l2_assertions" in results:
        compact_results["l2_assertions"] = _compact_assertions(
            results.get("l2_assertions"), max_items=max_items, max_text_chars=max_text_chars
        )
    if "l2_experiences" in results:
        compact_results["l2_experiences"] = _compact_experiences(
            results.get("l2_experiences"), max_items=max_items, max_text_chars=max_text_chars
        )
    if "l3_reflections" in results:
        compact_results["l3_reflections"] = _compact_reflections(
            results.get("l3_reflections"), max_items=max_items, max_text_chars=max_text_chars
        )
    if "l4_procedures" in results:
        compact_results["l4_procedures"] = _compact_procedures(
            results.get("l4_procedures"), max_items=max_items, max_text_chars=max_text_chars
        )
    return compact_results


def _merged_trace(results: Dict[str, Any], data: Dict[str, Any]) -> dict[str, Any]:
    merged_trace: dict[str, Any] = {}
    if isinstance(results.get("trace"), dict):
        merged_trace.update(results.get("trace") or {})
    if isinstance(data.get("meta"), dict):
        merged_trace.update(data.get("meta") or {})
    return merged_trace


__all__ = ["compact_memory_tool_data"]
