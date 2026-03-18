"""Deterministic context bundle collection for L2 reference resolution."""

from __future__ import annotations

import json
from typing import Any, Iterable

from ..event_contracts import MemoryEvent
from .context_bundle import ContextBundle, ContextEntity, ResolvedContextRef


def collect_context_bundle(
    *,
    event: MemoryEvent,
    recent_messages: list[dict[str, Any]] | None = None,
    recent_entities: list[dict[str, Any]] | None = None,
    live_context_entities: list[ContextEntity] | None = None,
    source_event_ids: Iterable[str] | None = None,
) -> ContextBundle:
    """Collect a minimal deterministic context bundle for one event."""

    pronoun_bindings: list[dict[str, Any]] = []
    text = str(event.raw_content or "")
    if "我" in text:
        pronoun_bindings.append(
            {
                "surface": "我",
                "resolved_ref": event.memory_owner_id or "user:self",
                "resolved_kind": "self_actor",
            }
        )

    return ContextBundle(
        recent_messages=list(recent_messages or []),
        recent_entities=list(recent_entities or []),
        live_context_entities=list(live_context_entities or []),
        pronoun_bindings=pronoun_bindings,
        source_event_ids=list(source_event_ids or []),
    )


def resolve_direct_context_refs(*, event: MemoryEvent, bundle: ContextBundle) -> list[ResolvedContextRef]:
    """Resolve deterministic direct references without invoking an LLM."""

    resolved: list[ResolvedContextRef] = []
    text = _reference_evidence_text(event)

    for binding in bundle.pronoun_bindings:
        resolved.append(
            ResolvedContextRef(
                surface=str(binding["surface"]),
                reference_type="self_actor" if binding.get("resolved_kind") == "self_actor" else "direct_binding",
                resolved_ref=str(binding["resolved_ref"]),
                resolved_kind=str(binding["resolved_kind"]),
                confidence=1.0,
                evidence_text=text,
            )
        )

    if "这种天气" in text:
        weather_contexts = [item for item in bundle.live_context_entities if item.kind == "weather_state"]
        if len(weather_contexts) == 1:
            resolved.append(
                ResolvedContextRef(
                    surface="这种天气",
                    reference_type="context_entity",
                    resolved_ref=weather_contexts[0].context_id,
                    resolved_kind=weather_contexts[0].kind,
                    confidence=0.95,
                    evidence_text=text,
                )
            )

    if "这道菜" in text:
        food_entities = [item for item in bundle.recent_entities if str(item.get("entity_type")) == "food"]
        if food_entities:
            latest_food = food_entities[-1]
            resolved_ref = str(latest_food.get("entity_id") or latest_food.get("resolved_entity_id") or "").strip()
            if resolved_ref:
                resolved.append(
                    ResolvedContextRef(
                        surface="这道菜",
                        reference_type="canonical_entity",
                        resolved_ref=resolved_ref,
                        resolved_kind="food",
                        confidence=0.9,
                        evidence_text=text,
                    )
                )

    return resolved


def _reference_evidence_text(event: MemoryEvent) -> str:
    payload_text = str(event.structured_payload or "").strip()
    if payload_text:
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            for key in ("message", "summary", "response", "text"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return str(event.raw_content or "")


__all__ = [
    "collect_context_bundle",
    "resolve_direct_context_refs",
]
