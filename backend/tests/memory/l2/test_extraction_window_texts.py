"""L2 reads the pinned capture-time full text for extraction (RFC #56 P3).

The event window feeds phase1/direct-write off ``texts``. When a source pinned a
full body for an event (obsidian note, git commit), L2 should extract against the
frozen full text, not the lean L1 summary — falling back to ``content`` otherwise.
"""
from __future__ import annotations

from types import SimpleNamespace

from magi.memory.l2.pipeline.extraction import resolve_window_texts


def _ev(event_id: str, content: str) -> SimpleNamespace:
    return SimpleNamespace(event_id=event_id, content=content)


def test_prefers_pinned_full_text_over_lean_content() -> None:
    events = [_ev("a", "lean summary A"), _ev("b", "lean summary B")]
    pinned = {"a": "FULL FROZEN BODY A"}
    assert resolve_window_texts(events, pinned) == ["FULL FROZEN BODY A", "lean summary B"]


def test_falls_back_to_content_when_no_pinned_payload() -> None:
    events = [_ev("a", "summary A")]
    assert resolve_window_texts(events, {}) == ["summary A"]


def test_empty_pinned_value_does_not_blank_out_text() -> None:
    events = [_ev("a", "summary A")]
    assert resolve_window_texts(events, {"a": ""}) == ["summary A"]
