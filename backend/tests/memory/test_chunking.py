from __future__ import annotations

from magi.memory.chunking import ChunkedText, chunk_text


def test_chunk_text_returns_single_chunk_for_short_text() -> None:
    text = "short memory note"

    chunks = chunk_text(text, max_chars=80, overlap_chars=10)

    assert chunks == [
        ChunkedText(
            chunk_id="chunk-0",
            text="short memory note",
            chunk_index=0,
            char_start=0,
            char_end=len(text),
            token_estimate=max(1, len(text) // 4),
        )
    ]


def test_chunk_text_preserves_overlap_for_long_text() -> None:
    text = "A" * 120 + " " + "B" * 120 + " " + "C" * 120

    chunks = chunk_text(text, max_chars=150, overlap_chars=30)

    assert len(chunks) >= 3
    assert chunks[0].chunk_index == 0
    assert chunks[1].chunk_index == 1
    assert chunks[0].char_end > chunks[1].char_start
    assert chunks[1].char_end > chunks[2].char_start
    assert chunks[-1].char_end == len(text)
