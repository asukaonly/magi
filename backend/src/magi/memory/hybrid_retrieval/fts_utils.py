"""FTS5 tokenization utilities using jieba for Chinese text segmentation."""

from __future__ import annotations

import re


# English stop words that add noise to FTS5 queries.
_FTS_STOP_WORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "can", "could",
    "did", "do", "does", "for", "from", "had", "has", "have", "he", "her",
    "him", "his", "how", "i", "if", "in", "into", "is", "it", "its", "me",
    "my", "no", "not", "of", "on", "or", "our", "shall", "she", "so",
    "some", "than", "that", "the", "their", "them", "then", "there", "these",
    "they", "this", "to", "us", "was", "we", "were", "what", "when", "where",
    "which", "who", "why", "will", "with", "would", "you", "your",
})


def _stem_english_token(token: str) -> str:
    """Lightweight English stemmer for FTS query expansion.

    Strips common inflectional suffixes so the stem can be used alongside
    the original token in an OR group.  Only applied to tokens > 3 chars.

    NOTE: this stemmer is paired with ``answerability._normalize_query_token``.
    Both strip the same set of inflections, but this one stops at the bare
    stem because FTS5 prefix wildcards (``mak*``) cover the silent-``e``
    surface form at query time, while the answerability rerank does
    token-equality and therefore re-attaches ``e``. If you change one,
    audit the other (M3 finding).
    """
    t = token.lower()
    if len(t) <= 3:
        return t
    if t.endswith("ied") and len(t) > 4:
        return f"{t[:-3]}y"
    if t.endswith("ing") and len(t) > 5:
        stem = t[:-3]
        # Doubled consonant: running→runn→run, swimming→swimm→swim
        if len(stem) >= 2 and stem[-1] == stem[-2] and stem[-1] not in "aeiou":
            return stem[:-1]
        return stem
    if t.endswith("ed") and len(t) > 4:
        if t[-3] == t[-4]:
            return t[:-3]
        if t[:-2].endswith("e"):
            return t[:-1]
        return t[:-2]
    if t.endswith("ies") and len(t) > 4:
        return f"{t[:-3]}y"
    if t.endswith("es") and len(t) > 4:
        return t[:-2]
    if t.endswith("s") and len(t) > 4 and not t.endswith("ss"):
        return t[:-1]
    return t


def _is_latin_token(token: str) -> bool:
    """Return True if token consists entirely of ASCII letters."""
    return bool(token) and all(c.isascii() and c.isalpha() for c in token)


def build_stemmed_fts_query(escaped_query: str) -> str:
    """Build an FTS5 query that matches both original tokens and their stems.

    Stop words are removed.  For each remaining Latin token whose stem differs
    from the original, a prefix query ``stem*`` is emitted.  For Latin tokens
    whose stem is unchanged but are longer than 4 characters, the last
    character is chopped for a prefix query to catch inflections
    (e.g. ``graduate`` → ``graduat*`` matches ``graduated``).

    CJK and mixed tokens are kept as exact matches.

    Example::

        "What degree did I graduate with"
        → "degre* graduat*"
    """
    tokens = escaped_query.split()
    parts: list[str] = []
    for token in tokens:
        lowered = token.lower()
        if lowered in _FTS_STOP_WORDS:
            continue
        if _is_latin_token(lowered):
            stem = _stem_english_token(lowered)
            if stem != lowered and len(stem) >= 3:
                parts.append(f"{stem}*")
            elif len(lowered) > 4:
                # No known suffix but long enough — chop 1 char for prefix
                parts.append(f"{lowered[:-1]}*")
            else:
                parts.append(lowered)
        else:
            # CJK / mixed → exact match
            parts.append(lowered)
    return " ".join(parts)


def build_exact_fts_query(escaped_query: str) -> str:
    """Build an FTS5 AND query with exact tokens (no prefix stemming).

    Stop words are removed.  Remaining tokens are kept as-is without
    prefix truncation or stem expansion.  Stricter than
    ``build_stemmed_fts_query`` — useful when prefix wildcards would
    introduce too much noise (e.g. ``crown`` stays ``crown`` instead of
    becoming ``crow*``).
    """
    tokens = escaped_query.split()
    parts: list[str] = []
    for token in tokens:
        lowered = token.lower()
        if lowered in _FTS_STOP_WORDS:
            continue
        parts.append(lowered)
    return " ".join(parts)


def build_or_fts_query(escaped_query: str) -> str:
    """Build an OR-mode FTS5 fallback query with stop words removed and stems added."""
    tokens = escaped_query.split()
    terms: list[str] = []
    for token in tokens:
        lowered = token.lower()
        if lowered in _FTS_STOP_WORDS:
            continue
        if _is_latin_token(lowered):
            stem = _stem_english_token(lowered)
            if stem != lowered and len(stem) >= 3:
                term = f"{stem}*"
            elif len(lowered) > 4:
                term = f"{lowered[:-1]}*"
            else:
                term = lowered
        else:
            term = lowered
        if term not in terms:
            terms.append(term)
    return " OR ".join(terms)


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
    cleaned = re.sub(r"[\'’*^?()\"{}[\]|+\-!~@#$%&,.;:，。；：、】【、\\/]", " ", query)
    # Collapse multiple spaces
    return re.sub(r"\s+", " ", cleaned).strip()
