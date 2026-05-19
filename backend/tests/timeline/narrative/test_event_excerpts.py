"""Tests for the L1 event excerpt packer used by the diary LLM prompt."""

from __future__ import annotations

from magi.timeline.narrative.event_excerpts import build_excerpts


def _event(content: str, *, ts: float = 0.0) -> dict:
    return {"content": content, "timestamp": ts}


def test_returns_empty_for_no_events():
    assert build_excerpts([]) == []


def test_skips_events_with_empty_or_non_string_content():
    events = [
        _event(""),
        _event("   "),
        {"content": None, "timestamp": 1.0},
        {"content": 42, "timestamp": 2.0},
    ]
    assert build_excerpts(events) == []


def test_picks_longest_content_first_then_orders_chronologically():
    events = [
        _event("short", ts=100.0),
        _event("a longer and more informative content string", ts=50.0),
        _event("middling content here", ts=200.0),
    ]
    result = build_excerpts(events, max_excerpts=3)
    # All three kept (no dupes, all under cap); chronological order
    assert result == [
        "a longer and more informative content string",
        "short",
        "middling content here",
    ]


def test_dedup_by_40char_prefix_kills_repeat_visits():
    """Same browser tab visited 9 times produces 9 events with identical title prefix."""
    events = [
        _event("Cursor Ultra能用多少刀? - 搞七捻三 - LINUX DO 访问 1", ts=1.0),
        _event("Cursor Ultra能用多少刀? - 搞七捻三 - LINUX DO 访问 2", ts=2.0),
        _event("Cursor Ultra能用多少刀? - 搞七捻三 - LINUX DO 访问 3", ts=3.0),
        _event("不同的页面：sleep agency 论文导读", ts=4.0),
    ]
    result = build_excerpts(events, max_excerpts=5)
    # Two unique prefixes survive
    assert len(result) == 2
    # Chronologically the Cursor one is first
    assert result[0].startswith("Cursor Ultra")
    assert "sleep agency" in result[1]


def test_respects_max_excerpts_cap():
    events = [
        _event(f"unique content number {i} with extra padding so prefixes differ", ts=float(i))
        for i in range(20)
    ]
    result = build_excerpts(events, max_excerpts=3)
    assert len(result) == 3


def test_truncates_long_content_with_ellipsis():
    long = "a" * 200
    events = [_event(long, ts=1.0)]
    result = build_excerpts(events, max_excerpts=1, max_chars_per_excerpt=20)
    assert len(result) == 1
    assert result[0].endswith("…")
    assert len(result[0]) == 20


def test_does_not_truncate_short_content():
    events = [_event("short text", ts=1.0)]
    result = build_excerpts(events, max_excerpts=1, max_chars_per_excerpt=80)
    assert result == ["short text"]


def test_handles_missing_timestamp_gracefully():
    events = [
        {"content": "no timestamp here"},
        {"content": "has timestamp", "timestamp": 100.0},
    ]
    result = build_excerpts(events, max_excerpts=2)
    # Both kept; sorted chronologically with missing ts treated as 0
    assert result == ["no timestamp here", "has timestamp"]


def test_dedup_is_case_insensitive():
    events = [
        _event("GitHub Copilot Documentation Overview", ts=1.0),
        _event("github copilot documentation overview", ts=2.0),
    ]
    result = build_excerpts(events, max_excerpts=5)
    assert len(result) == 1
