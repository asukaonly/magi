from __future__ import annotations

from magi.memory.embedding.chunking import ChunkedText, chunk_sentences, chunk_text


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


# ---------------------------------------------------------------------------
# chunk_sentences tests
# ---------------------------------------------------------------------------


def test_chunk_sentences_empty_text() -> None:
    assert chunk_sentences("") == []
    assert chunk_sentences(None) == []  # type: ignore[arg-type]


def test_chunk_sentences_no_boundary() -> None:
    """Single sentence with no EOS punctuation → 1 chunk."""
    text = "just a fragment without punctuation"
    chunks = chunk_sentences(text)
    assert len(chunks) == 1
    assert chunks[0].text == text
    assert chunks[0].chunk_index == 0


def test_chunk_sentences_english_multi_sentence() -> None:
    """Multiple English sentences are split at EOS punctuation."""
    text = (
        "I'm looking for Mike Trout's stats. "
        "Can you tell me his batting average? "
        "By the way, I have 15 autographed baseballs since three months ago!"
    )
    chunks = chunk_sentences(text)
    assert len(chunks) == 3
    assert "Mike Trout" in chunks[0].text
    assert "batting average" in chunks[1].text
    assert "15 autographed baseballs" in chunks[2].text
    # Indexes are sequential.
    for i, c in enumerate(chunks):
        assert c.chunk_index == i
        assert c.chunk_id == f"chunk-{i}"


def test_chunk_sentences_cjk_punctuation() -> None:
    """CJK EOS punctuation (。！？) splits correctly."""
    text = "我喜欢螺蛳粉。今天天气真好！你觉得呢？"
    chunks = chunk_sentences(text)
    assert len(chunks) == 3
    assert "螺蛳粉" in chunks[0].text
    assert "天气" in chunks[1].text
    assert "你觉得呢" in chunks[2].text


def test_chunk_sentences_short_merge() -> None:
    """Sentences shorter than min_chars are merged into the previous chunk."""
    text = "This is a long enough sentence that stands on its own. OK. Another real sentence here."
    chunks = chunk_sentences(text)
    # "OK." (3 chars) should merge into the preceding sentence.
    assert len(chunks) == 2
    assert "OK." in chunks[0].text
    assert "Another real sentence" in chunks[1].text


def test_chunk_sentences_paragraph_break() -> None:
    """Double newlines split into separate chunks."""
    text = "First paragraph content here\n\nSecond paragraph content here"
    chunks = chunk_sentences(text)
    assert len(chunks) == 2
    assert "First" in chunks[0].text
    assert "Second" in chunks[1].text


def test_chunk_sentences_char_offsets_cover_full_text() -> None:
    """char_start/char_end span the original text without gaps or overlaps."""
    text = "Hello world. Nice to meet you! How are you doing today?"
    chunks = chunk_sentences(text)
    assert len(chunks) >= 2
    for c in chunks:
        assert text[c.char_start : c.char_end] == c.text


def test_chunk_sentences_mixed_english_cjk() -> None:
    """Mixed English and CJK punctuation both trigger splits."""
    text = "I went to Tokyo. 东京很好玩。It was amazing!"
    chunks = chunk_sentences(text)
    assert len(chunks) == 3


def test_chunk_sentences_real_longmemeval_case() -> None:
    """Reproduce the 0ddfec37 missed-session pattern from LongMemEval."""
    text = (
        "I'm looking for some information on Mike Trout's latest stats. "
        "Can you tell me his current batting average and how many home runs "
        "he has this season? By the way, I just got a signed baseball of his "
        "last week and it's a great addition to my collection - that's 15 "
        "autographed baseballs since I started collecting three months ago!"
    )
    chunks = chunk_sentences(text)
    # The key fact must be in its own chunk, not drowned by Mike Trout stats.
    baseball_chunks = [c for c in chunks if "autographed baseballs" in c.text]
    assert len(baseball_chunks) == 1
    # And it should NOT contain "Mike Trout's latest stats".
    assert "Mike Trout's latest stats" not in baseball_chunks[0].text
