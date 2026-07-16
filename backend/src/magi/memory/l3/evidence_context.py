"""Non-evidence interpretation context carried alongside L3 evidence items."""

from __future__ import annotations

from collections.abc import Mapping

from ...events.first_context import first_context_from_metadata


def first_context_interpretation_context(
    event: Mapping[str, object],
) -> dict[str, str] | None:
    """Return controlled question context without promoting it to evidence."""
    context = first_context_from_metadata(event.get("metadata_json"))
    if context is None:
        return None
    return {
        "kind": "first_context_question",
        "question_id": context["question_id"],
        "question_text": context["question_text"],
        "evidence_semantics": "interpretation_context_only",
    }


__all__ = ["first_context_interpretation_context"]
