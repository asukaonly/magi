"""DeliveryChunk tests — frozen streaming-fragment dataclass."""
from __future__ import annotations

from magi_plugin_sdk.delivery import DeliveryChunk


def test_construct_and_read_all_fields() -> None:
    """Construct a chunk and read text/is_final/seq back unchanged."""
    chunk = DeliveryChunk(text="hi", is_final=False, seq=0)
    assert chunk.text == "hi"
    assert chunk.is_final is False
    assert chunk.seq == 0


def test_mutation_raises_because_frozen() -> None:
    """Frozen dataclass: assigning to any field must raise."""
    chunk = DeliveryChunk(text="hi", is_final=False, seq=0)
    raised_text = False
    try:
        chunk.text = "bye"  # type: ignore[misc]
    except Exception:
        raised_text = True
    assert raised_text, "expected mutation of .text to raise on frozen dataclass"

    raised_is_final = False
    try:
        chunk.is_final = True  # type: ignore[misc]
    except Exception:
        raised_is_final = True
    assert raised_is_final, "expected mutation of .is_final to raise on frozen dataclass"

    raised_seq = False
    try:
        chunk.seq = 1  # type: ignore[misc]
    except Exception:
        raised_seq = True
    assert raised_seq, "expected mutation of .seq to raise on frozen dataclass"


def test_final_chunk_with_empty_text_is_allowed() -> None:
    """A boundary-only final chunk may carry an empty text."""
    chunk = DeliveryChunk(text="", is_final=True, seq=7)
    assert chunk.text == ""
    assert chunk.is_final is True
    assert chunk.seq == 7
