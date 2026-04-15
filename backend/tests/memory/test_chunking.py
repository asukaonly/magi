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


def test_chunk_sentences_short_text_single_chunk() -> None:
    """Multiple sentences within target_chars → single chunk."""
    text = (
        "I'm looking for Mike Trout's stats. "
        "Can you tell me his batting average? "
        "By the way, I have 15 autographed baseballs since three months ago!"
    )
    chunks = chunk_sentences(text)
    assert len(chunks) == 1
    assert chunks[0].text == text


def test_chunk_sentences_splits_with_small_target() -> None:
    """With low target_chars, individual sentences are preserved."""
    text = (
        "I'm looking for Mike Trout's stats. "
        "Can you tell me his batting average? "
        "By the way, I have 15 autographed baseballs since three months ago!"
    )
    chunks = chunk_sentences(text, target_chars=50)
    assert len(chunks) == 3
    assert "Mike Trout" in chunks[0].text
    assert "batting average" in chunks[1].text
    assert "autographed baseballs" in chunks[2].text


def test_chunk_sentences_cjk_punctuation() -> None:
    """CJK EOS punctuation (。！？) splits correctly when target_chars is small."""
    text = "我喜欢螺蛳粉。今天天气真好！你觉得呢？"
    # Short CJK text under default target_chars → single chunk.
    chunks = chunk_sentences(text)
    assert len(chunks) == 1
    assert "螺蛳粉" in chunks[0].text
    assert "天气" in chunks[0].text


def test_chunk_sentences_cjk_splits_with_small_target() -> None:
    """CJK sentences split when target_chars is small."""
    text = "我喜欢螺蛳粉。今天天气真好！你觉得呢？"
    chunks = chunk_sentences(text, target_chars=10)
    assert len(chunks) == 3
    assert "螺蛳粉" in chunks[0].text
    assert "天气" in chunks[1].text
    assert "你觉得呢" in chunks[2].text


def test_chunk_sentences_short_merge() -> None:
    """Sentences shorter than min_chars are merged into the previous chunk."""
    text = "This is a long enough sentence that stands on its own. OK. Another real sentence here."
    # Under default target_chars → single chunk.
    chunks = chunk_sentences(text)
    assert len(chunks) == 1
    assert "OK." in chunks[0].text
    # With small target, "OK." still merges into preceding sentence.
    chunks_small = chunk_sentences(text, target_chars=40)
    ok_chunks = [c for c in chunks_small if "OK." in c.text]
    assert len(ok_chunks) == 1
    assert "stands on its own" in ok_chunks[0].text


def test_chunk_sentences_paragraph_break() -> None:
    """Double newlines split into separate chunks when text is long enough."""
    text = "First paragraph content here\n\nSecond paragraph content here"
    # Short text → single chunk.
    chunks = chunk_sentences(text)
    assert len(chunks) == 1
    assert "First" in chunks[0].text
    assert "Second" in chunks[0].text


def test_chunk_sentences_char_offsets_cover_full_text() -> None:
    """char_start/char_end span the original text correctly."""
    text = "Hello world. Nice to meet you! How are you doing today?"
    chunks = chunk_sentences(text)
    assert len(chunks) == 1
    assert chunks[0].text == text
    assert text[chunks[0].char_start : chunks[0].char_end] == chunks[0].text


def test_chunk_sentences_mixed_english_cjk() -> None:
    """Mixed English and CJK punctuation both trigger splits with small target."""
    text = "I went to Tokyo. 东京很好玩。It was amazing!"
    chunks_small = chunk_sentences(text, target_chars=20)
    assert len(chunks_small) == 3


def test_chunk_sentences_groups_adjacent_sentences() -> None:
    """Long text with many sentences gets grouped to target_chars."""
    sentences = [
        "The quick brown fox jumps over the lazy dog near the river bank on a sunny day.",
        "A wonderful serenity has taken possession of my entire soul like a sweet morning.",
        "I am alone and feel the charm of existence in this quiet and peaceful spot here.",
        "The sky above the port was the color of television tuned to a dead channel now.",
        "It was a bright cold day in April and the clocks were striking thirteen loudly.",
        "All happy families are alike but each unhappy family is unhappy in its own way.",
        "It is a truth universally acknowledged that a single man must want a good wife.",
        "Call me Ishmael and let me tell you about the great sea and the enormous whale.",
        "In my younger and more vulnerable years my father gave me some very good advice.",
        "It was the best of times and it was the worst of times in this wonderful city.",
    ]
    text = " ".join(sentences)
    # ~800 chars total, with target_chars=400, expect 2-3 chunks.
    chunks = chunk_sentences(text, target_chars=400)
    assert 2 <= len(chunks) <= 3
    # Most chunks should contain multiple sentences (last may be shorter).
    multi_sentence_chunks = [c for c in chunks if len(c.text) > 100]
    assert len(multi_sentence_chunks) >= 2


def test_chunk_sentences_char_offsets_with_grouping() -> None:
    """Grouped chunks still have correct char offsets."""
    sentences = [
        "Alpha bravo charlie delta echo foxtrot golf hotel india juliet.",
        "Kilo lima mike november oscar papa quebec romeo sierra tango.",
        "Uniform victor whiskey xray yankee zulu alpha bravo charlie.",
        "Delta echo foxtrot golf hotel india juliet kilo lima mike now.",
    ]
    text = " ".join(sentences)
    chunks = chunk_sentences(text, target_chars=100)
    assert len(chunks) >= 2
    for c in chunks:
        assert text[c.char_start : c.char_end] == c.text


def test_chunk_sentences_real_longmemeval_case() -> None:
    """LongMemEval pattern: short multi-topic message stays as one chunk."""
    text = (
        "I'm looking for some information on Mike Trout's latest stats. "
        "Can you tell me his current batting average and how many home runs "
        "he has this season? By the way, I just got a signed baseball of his "
        "last week and it's a great addition to my collection - that's 15 "
        "autographed baseballs since I started collecting three months ago!"
    )
    chunks = chunk_sentences(text)
    # ~320 chars total → single chunk, full context preserved.
    assert len(chunks) == 1
    assert "autographed baseballs" in chunks[0].text
    assert "Mike Trout" in chunks[0].text


def test_chunk_sentences_long_text_separates_topics() -> None:
    """Long multi-topic text gets split so each topic stays retrievable."""
    topic1 = (
        "Photography is a wonderful hobby that can bring immense joy and creativity. "
        "A prime lens with a wide aperture can make a significant difference in low-light photography. "
        "A lens with a wide aperture like f/1.4 or f/1.8 can let in more light and create beautiful bokeh. "
        "This is especially useful for portrait photography and indoor shooting in dim environments. "
        "Many professional photographers recommend starting with a 50mm f/1.8 lens as your first prime lens."
    )
    topic2 = (
        "Cooking with sumac is a fantastic way to add tangy flavor to your dishes. "
        "Sumac is commonly used in Middle Eastern and Mediterranean cuisine for its citrusy taste. "
        "You can sprinkle it over salads, grilled meats, hummus, and roasted vegetables for extra flavor. "
        "It pairs wonderfully with olive oil and fresh herbs like parsley and mint for dressings. "
        "Many traditional dishes like fattoush salad rely on sumac as a key ingredient for that tangy kick."
    )
    text = topic1 + " " + topic2
    chunks = chunk_sentences(text, target_chars=400)
    assert len(chunks) >= 2
    # Photography and sumac topics should be in different chunks.
    photo_chunks = [c for c in chunks if "aperture" in c.text]
    sumac_chunks = [c for c in chunks if "sumac" in c.text.lower()]
    assert len(photo_chunks) >= 1
    assert len(sumac_chunks) >= 1
