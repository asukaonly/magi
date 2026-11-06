"""Portable persistence values and deterministic row normalization."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChunkedText:
    """One chunk of a larger source text."""

    chunk_id: str
    text: str
    chunk_index: int
    char_start: int
    char_end: int
    token_estimate: int
