"""Request-local evidence labels; durable identities remain host-owned."""

from __future__ import annotations

from typing import Any

from .models import L2EventWindow


def evidence_ref_labels(
    window: L2EventWindow, context_messages: list[dict[str, Any]] | None
) -> dict[str, str]:
    """Assign stable short labels without modifying source message contents."""
    labels = {event.event_id: f"E{index}" for index, event in enumerate(window.events, 1)}
    for index, message in enumerate(context_messages or [], 1):
        event_id = str(message.get("event_id") or "").strip()
        if event_id:
            labels.setdefault(event_id, f"C{index}")
    return labels


def restore_evidence_refs(payload: dict[str, Any], labels: dict[str, str]) -> None:
    """Decode only reference fields, never quotes, names or other evidence text."""
    reverse = {label: event_id for event_id, label in labels.items()}
    for family in ("fact_claims", "resolved_refs"):
        items = payload.get(family)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            for key in ("supporting_event_ids", "antecedent_event_ids"):
                values = item.get(key)
                if isinstance(values, list):
                    item[key] = [reverse.get(str(value).lstrip("#"), value) for value in values]
