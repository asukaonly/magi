"""Preserve rich-text attribution in a frozen document evidence projection."""

from __future__ import annotations

import re
from typing import Any

from ..l2.pipeline.history_markdown import (
    HistoryDocumentSpanKind,
    classify_history_document_spans,
)

_CONTAINER_TYPES = frozenset(
    {
        "doc",
        "paragraph",
        "heading",
        "bulletList",
        "orderedList",
        "listItem",
        "blockquote",
        "codeBlock",
    }
)
_MARK_TYPES = frozenset({"bold", "italic", "strike", "link", "code"})


def project_rich_text_evidence(body: str, document: dict[str, Any]) -> str:
    """Freeze quote/code boundaries while checking the saved plain-text body.

    Text leaves must account for the complete body in source order. Only
    whitespace may separate them. Unsupported or inconsistent documents must not
    silently grant authorship to their flattened text.
    """
    if document.get("type") != "doc":
        raise ValueError("rich-text evidence requires a document root")
    leaves: list[tuple[str, bool]] = []
    _collect_leaves(document, excluded=False, leaves=leaves, depth=0)
    cursor = 0
    excluded_ranges: list[tuple[int, int]] = []
    for text, excluded in leaves:
        start = body.find(text, cursor)
        if start < 0 or body[cursor:start].strip():
            raise ValueError("rich-text evidence does not match the saved body")
        end = start + len(text)
        if excluded:
            if excluded_ranges and not body[excluded_ranges[-1][1] : start].strip():
                excluded_ranges[-1] = (excluded_ranges[-1][0], end)
            else:
                excluded_ranges.append((start, end))
        cursor = end
    if body[cursor:].strip():
        raise ValueError("rich-text evidence leaves unaccounted body text")
    parts: list[str] = []
    cursor = 0
    projected_offset = 0
    protected_ranges: list[tuple[int, int]] = []
    for start, end in excluded_ranges:
        prose = body[cursor:start]
        parts.append(prose)
        projected_offset += len(prose)
        excluded_text = body[start:end]
        # A longer fence cannot be closed by backticks inside the source text.
        fence_length = max((len(run) + 1 for run in re.findall(r"`+", excluded_text)), default=3)
        fence = "`" * max(3, fence_length)
        prefix = f"\n\n{fence}quoted\n"
        block = f"{prefix}{excluded_text}\n{fence}\n\n"
        protected_ranges.append(
            (projected_offset + len(prefix), projected_offset + len(prefix) + len(excluded_text))
        )
        parts.append(block)
        projected_offset += len(block)
        cursor = end
    parts.append(body[cursor:])
    projected = "".join(parts)
    # Literal Markdown in other text may change the parser's fence state. Check
    # the same attribution spans L2 will use instead of trusting serialization.
    range_index = 0
    for span in classify_history_document_spans(projected):
        while (
            range_index < len(protected_ranges) and protected_ranges[range_index][1] <= span.start
        ):
            range_index += 1
        if range_index == len(protected_ranges):
            break
        if (
            span.kind is HistoryDocumentSpanKind.AUTHOR_PROSE
            and protected_ranges[range_index][0] < span.end
        ):
            raise ValueError("rich-text quote boundaries are ambiguous")
    return projected


def _collect_leaves(
    node: object, *, excluded: bool, leaves: list[tuple[str, bool]], depth: int
) -> None:
    if not isinstance(node, dict) or depth > 100:
        raise ValueError("invalid rich-text evidence structure")
    kind = node.get("type")
    if not isinstance(kind, str):
        raise ValueError("invalid rich-text evidence node type")
    marks = node.get("marks", [])
    if not isinstance(marks, list) or any(
        not isinstance(mark, dict)
        or not isinstance(mark.get("type"), str)
        or mark["type"] not in _MARK_TYPES
        for mark in marks
    ):
        raise ValueError("unsupported rich-text evidence mark")
    excluded = (
        excluded
        or kind in {"blockquote", "codeBlock"}
        or any(mark.get("type") == "code" for mark in marks)
    )
    if kind == "text":
        text = node.get("text")
        if not isinstance(text, str) or node.get("content"):
            raise ValueError("invalid rich-text evidence leaf")
        if text:
            leaves.append((text, excluded))
        return
    if kind in {"hardBreak", "horizontalRule"}:
        if node.get("content") or node.get("text"):
            raise ValueError("invalid rich-text evidence separator")
        return
    if kind not in _CONTAINER_TYPES:
        raise ValueError("unsupported rich-text evidence node")
    children = node.get("content", [])
    if not isinstance(children, list) or node.get("text"):
        raise ValueError("invalid rich-text evidence content")
    for child in children:
        _collect_leaves(child, excluded=excluded, leaves=leaves, depth=depth + 1)
