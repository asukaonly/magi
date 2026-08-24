"""Strict text fallback for the explicit run-cancel control protocol."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

_STRICT_NORMALIZE_RE = re.compile(
    r"[\s\.,!\?;:\-_\"'`~@#\$%\^&\*\(\)\[\]\{\}<>/\\|"
    "，。！？、；：\"'「」『』【】（）《》…—–～]+"
)
_STRICT_CLAUSE_SPLIT_RE = re.compile(r"[\s]*[\.,!\?;:，。！？、；：]+[\s]*")
_PHRASES_FILE = Path(__file__).with_name("cancel_phrases.yaml")


@lru_cache(maxsize=1)
def load_strict_cancel_phrases() -> frozenset[str]:
    """Load the exact normalized phrases accepted as cancel controls."""

    try:
        raw = yaml.safe_load(_PHRASES_FILE.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return frozenset()
    phrases: set[str] = set()
    for bucket in raw.values() if isinstance(raw, dict) else ():
        if isinstance(bucket, list):
            phrases.update(
                str(entry or "").strip()
                for entry in bucket
                if str(entry or "").strip()
            )
    return frozenset(phrases)


def is_strict_cancel_text(user_text: str) -> bool:
    """Return whether the complete message is an unambiguous cancel control."""

    normalized = _normalize(user_text)
    phrases = load_strict_cancel_phrases()
    if normalized and normalized in phrases:
        return True
    clauses = [
        _normalize(clause)
        for clause in _STRICT_CLAUSE_SPLIT_RE.split(user_text)
        if _normalize(clause)
    ]
    return len(clauses) > 1 and all(clause in phrases for clause in clauses)


def _normalize(user_text: str) -> str:
    return _STRICT_NORMALIZE_RE.sub("", str(user_text or "").lower())


__all__ = ["is_strict_cancel_text", "load_strict_cancel_phrases"]
