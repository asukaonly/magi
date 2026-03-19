"""FTS5 tokenization utilities using jieba for Chinese text segmentation."""

from __future__ import annotations

import re


def tokenize_for_fts(text: str) -> str:
    """Segment text with jieba and join with spaces for FTS5 simple tokenizer.

    Uses jieba.cut_for_search for finer-grained segmentation suitable for
    search index construction. Falls back to the original text if jieba
    is not available.
    """
    if not text or not text.strip():
        return ""
    try:
        import jieba
        tokens = jieba.cut_for_search(text)
        return " ".join(t for t in tokens if t.strip())
    except ImportError:
        return text


def escape_fts_query(query: str) -> str:
    """Escape special FTS5 characters in a query string.

    FTS5 uses characters like *, ^, (, ), ", etc. as operators.
    We strip them to avoid syntax errors.
    """
    # Remove FTS5 special chars that could cause syntax errors
    cleaned = re.sub(r'[*^?()"{}[\]|+\-!~@#$%&\\]', " ", query)
    # Collapse multiple spaces
    return re.sub(r"\s+", " ", cleaned).strip()
