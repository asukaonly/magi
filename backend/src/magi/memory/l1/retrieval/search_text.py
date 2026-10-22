"""Canonical event text used by lexical and semantic retrieval."""

from __future__ import annotations

from ...embedding.embedding_text_builders import build_l1_retrieval_terms_text
from ...event_contracts import MemoryEvent


def get_search_text(event: MemoryEvent) -> str:
    text = str(event.content or "").strip()
    retrieval_terms = build_l1_retrieval_terms_text(event)
    if retrieval_terms and retrieval_terms.lower() not in text.lower():
        text = f"{text} {retrieval_terms}".strip()
    return compose_search_text(text, event.author_type, event.content_type)

def compose_search_text(content: str, author_type: str, content_type: str) -> str:
    text = str(content or "").strip()
    labels = " ".join(
        part
        for part in (str(author_type or "").strip(), str(content_type or "").strip())
        if part
    )
    if text and labels:
        return f"{text} {labels}"
    return text or labels
