"""Host-owned rendering for source activity projections."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .source_base import Source
from .source_output import (
    ActivityFacet,
    SourceOutput,
    SourceOutputMetadata,
)

_RENDERER_VERSION = "source_activity_v1"
_ASCII_RE = re.compile(r"[A-Za-z0-9]")


@dataclass(slots=True, frozen=True)
class SourceProjection:
    """Host-rendered source projection used for memory and timeline writes."""

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
    def from_dict(cls, data: dict[str, Any]) -> "SourceProjection":
        return cls(
            title=str(data["title"]),
            summary=str(data["summary"]),
            content=str(data["content"]),
            embedding_head=str(data["embedding_head"]),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass(slots=True, frozen=True)
class _SourceProjectionText:
    title: str
    summary: str
    content: str
    embedding_head: str


def build_source_projection(
    source: Source,
    output: SourceOutput,
    metadata: SourceOutputMetadata | None = None,
) -> SourceProjection:
    """Render canonical display and embedding projections for one source output."""
    _validate_output_contract(output)
    text = _build_projection_text(source=source, output=output)
    projection_metadata = _build_projection_metadata(
        source=source,
        output=output,
        metadata=metadata,
        embedding_head=text.embedding_head,
        summary=text.summary,
    )

    return SourceProjection(
        title=text.title,
        summary=text.summary,
        content=text.content,
        embedding_head=text.embedding_head,
        metadata=projection_metadata,
    )


def _build_projection_text(
    *,
    source: Source,
    output: SourceOutput,
) -> _SourceProjectionText:
    display_prefix = _join_with_space(
        _display_label(source, output.activity.source),
        _display_label(source, output.activity.action),
    )
    embedding_head = _join_embedding_head(
        _embedding_label(output.activity.source),
        _embedding_label(output.activity.action),
    )

    narration_title = str(output.narration.title or "").strip()
    narration_body = _normalize_body(
        output, display_prefix=display_prefix, embedding_head=embedding_head
    )
    presentation = output.timeline_presentation

    full_title = _compose_title(
        display_prefix=display_prefix,
        event_title=narration_title,
        fallback=str(output.source_type or "").strip(),
    )
    full_content = _compose_summary(
        display_prefix=display_prefix,
        body=narration_body,
        fallback_title=full_title,
    )

    title = full_title
    summary = full_content
    if presentation.mode in {"compact", "evidence_only"}:
        presentation_title = presentation.title or narration_title
        title = _compose_title(
            display_prefix=display_prefix,
            event_title=presentation_title,
            fallback=full_title,
        )
        presentation_summary_body = presentation.summary or presentation.title or narration_title
        summary = _compose_summary(
            display_prefix=display_prefix,
            body=presentation_summary_body or "",
            fallback_title=title,
        )

    return _SourceProjectionText(
        title=title,
        summary=summary,
        content=full_content,
        embedding_head=embedding_head,
    )


def _build_projection_metadata(
    *,
    source: Source,
    output: SourceOutput,
    metadata: SourceOutputMetadata | None,
    embedding_head: str,
    summary: str,
) -> dict[str, Any]:
    projection_metadata: dict[str, Any] = {
        "plugin_id": source.plugin_id,
        "source_id": source.source_id,
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
    presentation = output.timeline_presentation
    if presentation.mode != "full":
        projection_metadata["projection"]["timeline_presentation"] = {
            "mode": presentation.mode,
        }
    # Retrieval terms feed the L1 FTS index, so anything we want BM25 /
    # keyword paths to match must land here. Both producer-side tags
    # (``output.tags``, e.g. ``app_category:gaming`` from screen-time)
    # and host-attached metadata tags qualify.
    host_metadata_tags = list(metadata.tags) if metadata else []
    source_output_tags = list(output.tags or [])
    retrieval_terms = _normalize_retrieval_terms(source_output_tags + host_metadata_tags)
    if retrieval_terms:
        projection_metadata["projection"]["retrieval_terms"] = retrieval_terms

    return projection_metadata


def _validate_output_contract(output: SourceOutput) -> None:
    for facet_name, facet in (
        ("source", output.activity.source),
        ("action", output.activity.action),
    ):
        if not str(facet.code or "").strip():
            raise ValueError(f"Source activity facet '{facet_name}' must define a non-empty code")
        if not str(facet.i18n_key or "").strip():
            raise ValueError(
                f"Source activity facet '{facet_name}' must define a non-empty i18n_key"
            )
    if output.activity.object is not None:
        if not str(output.activity.object.code or "").strip():
            raise ValueError("Source activity object facet must define a non-empty code")
        if not str(output.activity.object.i18n_key or "").strip():
            raise ValueError("Source activity object facet must define a non-empty i18n_key")
    if not str(output.narration.body or "").strip() and not any(
        block.kind == "text" and str(block.value or "").strip() for block in output.content_blocks
    ):
        raise ValueError("Source narration must define a non-empty body or text content block")


def _display_label(source: Source, facet: ActivityFacet) -> str:
    fallback = facet.fallback or facet.code
    return source.t(facet.i18n_key, fallback=fallback).strip()


def _embedding_label(facet: ActivityFacet) -> str:
    return str(facet.embedding_fallback or facet.fallback or facet.code).strip()


def _normalize_body(
    output: SourceOutput,
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
            body = body[len(duplicate_prefix) :].strip()
    return body


def _compose_title(*, display_prefix: str, event_title: str, fallback: str) -> str:
    title = display_prefix or event_title or fallback
    if display_prefix and event_title:
        title = f"{display_prefix} · {event_title}"
    elif event_title:
        title = event_title
    return title.strip()


def _compose_summary(*, display_prefix: str, body: str, fallback_title: str) -> str:
    summary = display_prefix or body or fallback_title
    if display_prefix and body:
        summary = f"{display_prefix} {body}".strip()
    elif body:
        summary = body
    return summary.strip()


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
    "SourceProjection",
    "build_source_projection",
]
