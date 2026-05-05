"""Host-owned rendering for sensor activity projections."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..timeline.contracts import TimelineContentBlock, TimelineEvent
from .sensor_base import SensorBase
from .sensor_output import ActivityFacet, SensorOutput, SensorOutputMetadata

_RENDERER_VERSION = "sensor_activity_v1"
_ASCII_RE = re.compile(r"[A-Za-z0-9]")


@dataclass(slots=True, frozen=True)
class SensorProjection:
    """Host-rendered sensor projection used for memory and timeline writes."""

    title: str
    summary: str
    content: str
    embedding_head: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "content": self.content,
            "embedding_head": self.embedding_head,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SensorProjection":
        return cls(
            title=str(data["title"]),
            summary=str(data["summary"]),
            content=str(data["content"]),
            embedding_head=str(data["embedding_head"]),
            metadata=dict(data.get("metadata", {})),
        )


def build_sensor_projection(
    sensor: SensorBase,
    output: SensorOutput,
    metadata: SensorOutputMetadata | None = None,
) -> SensorProjection:
    """Render canonical display and embedding projections for one sensor output."""
    _validate_output_contract(output)

    display_prefix = _join_with_space(
        _display_label(sensor, output.activity.source),
        _display_label(sensor, output.activity.action),
    )
    embedding_head = _join_embedding_head(
        _embedding_label(output.activity.source),
        _embedding_label(output.activity.action),
    )

    narration_title = str(output.narration.title or "").strip()
    narration_body = _normalize_body(output, display_prefix=display_prefix, embedding_head=embedding_head)

    title = display_prefix or narration_title or str(output.source_type or "").strip()
    if display_prefix and narration_title:
        title = f"{display_prefix} · {narration_title}"
    elif narration_title:
        title = narration_title

    summary = display_prefix or narration_body or title
    if display_prefix and narration_body:
        summary = f"{display_prefix} {narration_body}".strip()
    elif narration_body:
        summary = narration_body

    projection_metadata: dict[str, Any] = {
        "plugin_id": sensor.plugin_id,
        "sensor_id": sensor.sensor_id,
        "activity": {
            "source_code": output.activity.source.code,
            "action_code": output.activity.action.code,
        },
        "projection": {
            "renderer_version": _RENDERER_VERSION,
        },
    }
    if output.activity.object is not None:
        projection_metadata["activity"]["object_code"] = output.activity.object.code
    if output.activity.qualifiers:
        projection_metadata["activity"]["qualifiers"] = dict(output.activity.qualifiers)
    if embedding_head and embedding_head != summary:
        projection_metadata["projection"]["embedding_head"] = embedding_head
    retrieval_terms = _normalize_retrieval_terms(metadata.tags if metadata else [])
    if retrieval_terms:
        projection_metadata["projection"]["retrieval_terms"] = retrieval_terms

    return SensorProjection(
        title=title,
        summary=summary,
        content=summary,
        embedding_head=embedding_head,
        metadata=projection_metadata,
    )


def build_sensor_timeline_event(
    event_id: str,
    output: SensorOutput,
    projection: SensorProjection,
    metadata: SensorOutputMetadata | None = None,
) -> TimelineEvent:
    """Build the timeline read model from a host-rendered sensor projection."""
    extra_entities = metadata.entities if metadata else []
    extra_tags = metadata.tags if metadata else []

    return TimelineEvent(
        event_id=event_id,
        source_type=output.source_type,
        source_item_id=output.source_item_id,
        occurred_at=output.occurred_at,
        captured_at=output.captured_at,
        title=projection.title,
        summary=projection.summary,
        retention_mode=output.domain_payload.get("retention_mode", "analyze_only"),
        raw_payload_ref=output.raw_payload_ref,
        content_blocks=[
            TimelineContentBlock(
                kind=block.kind,
                value=block.value,
                mime_type=block.mime_type,
            )
            for block in output.content_blocks
        ],
        entities=output.entities + extra_entities,
        tags=list(dict.fromkeys(output.tags + extra_tags)),
        privacy_labels=output.domain_payload.get("privacy_labels", []),
        processing_status={
            "stored": True,
            "analyzed": bool(metadata and (metadata.relation_candidates or metadata.fact_hints)),
        },
        provenance=output.provenance,
    )


def _validate_output_contract(output: SensorOutput) -> None:
    for facet_name, facet in (("source", output.activity.source), ("action", output.activity.action)):
        if not str(facet.code or "").strip():
            raise ValueError(f"Sensor activity facet '{facet_name}' must define a non-empty code")
        if not str(facet.i18n_key or "").strip():
            raise ValueError(f"Sensor activity facet '{facet_name}' must define a non-empty i18n_key")
    if output.activity.object is not None:
        if not str(output.activity.object.code or "").strip():
            raise ValueError("Sensor activity object facet must define a non-empty code")
        if not str(output.activity.object.i18n_key or "").strip():
            raise ValueError("Sensor activity object facet must define a non-empty i18n_key")
    if not str(output.narration.body or "").strip() and not any(
        block.kind == "text" and str(block.value or "").strip()
        for block in output.content_blocks
    ):
        raise ValueError("Sensor narration must define a non-empty body or text content block")


def _display_label(sensor: SensorBase, facet: ActivityFacet) -> str:
    fallback = facet.fallback or facet.code
    return sensor.t(facet.i18n_key, fallback=fallback).strip()


def _embedding_label(facet: ActivityFacet) -> str:
    return str(facet.embedding_fallback or facet.fallback or facet.code).strip()


def _normalize_body(
    output: SensorOutput,
    *,
    display_prefix: str,
    embedding_head: str,
) -> str:
    body = str(output.narration.body or "").strip()
    if not body:
        body = " ".join(
            str(block.value).strip()
            for block in output.content_blocks
            if block.kind == "text" and str(block.value or "").strip()
        ).strip()
    for duplicate_prefix in (display_prefix, embedding_head):
        if duplicate_prefix and body.startswith(duplicate_prefix):
            body = body[len(duplicate_prefix):].strip()
    return body


def _join_with_space(*parts: str) -> str:
    return " ".join(part for part in parts if str(part or "").strip()).strip()


def _join_embedding_head(*parts: str) -> str:
    normalized = [str(part or "").strip() for part in parts if str(part or "").strip()]
    if not normalized:
        return ""
    if any(_ASCII_RE.search(part) for part in normalized):
        return " ".join(normalized)
    return "".join(normalized)


def _normalize_retrieval_terms(values: list[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        term = str(value or "").strip()
        if not term:
            continue
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(term)
        if len(normalized) >= 8:
            break
    return normalized


__all__ = [
    "SensorProjection",
    "build_sensor_projection",
    "build_sensor_timeline_event",
]