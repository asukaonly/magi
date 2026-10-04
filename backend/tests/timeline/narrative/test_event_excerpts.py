"""Tests for the L1 event excerpt packer used by the diary LLM prompt."""

from __future__ import annotations

import pytest

from magi.timeline.narrative.event_excerpts import build_excerpts


def _event(content: str, *, ts: float = 0.0) -> dict:
    return {"content": content, "timestamp": ts}


@pytest.mark.parametrize(
    "events,expected",
    [
        ([], []),
        ([_event(""), _event("   "), {"content": None}, {"content": 42}], []),
        ([_event("  usable text  "), {"content": None}], ["usable text"]),
    ],
)
def test_normalization_keeps_only_nonempty_text(events, expected):
    assert build_excerpts(events) == expected


def test_selects_longest_candidates_before_putting_survivors_in_time_order():
    events = [
        _event("short", ts=100.0),
        _event("a longer and more informative content string", ts=200.0),
        _event("middling content here", ts=50.0),
    ]
    assert build_excerpts(events, max_excerpts=2) == [
        "middling content here",
        "a longer and more informative content string",
    ]


@pytest.mark.parametrize("duplicate", ["A" * 40 + " second visit", "a" * 40 + " second visit"])
def test_prefix_dedup_retains_one_representative_and_unrelated_content(duplicate):
    first = "A" * 40 + " initial page title with the longest useful description"
    events = [_event(first, ts=1.0), _event(duplicate, ts=2.0), _event("Unrelated page", ts=3.0)]
    assert build_excerpts(events, max_excerpts=5, max_chars_per_excerpt=200) == [
        first,
        "Unrelated page",
    ]


@pytest.mark.parametrize(
    "text,limit,expected",
    [
        ("a" * 200, 20, "a" * 19 + "…"),
        ("short text", 80, "short text"),
        ("边界正好", 4, "边界正好"),
        ("中文字符超长", 4, "中文字…"),
    ],
)
def test_excerpt_budget_preserves_prefix_and_only_marks_truncated_content(text, limit, expected):
    assert build_excerpts([_event(text, ts=1.0)], max_excerpts=1, max_chars_per_excerpt=limit) == [
        expected
    ]


def test_handles_missing_timestamp_gracefully():
    events = [
        {"content": "no timestamp here"},
        {"content": "has timestamp", "timestamp": 100.0},
    ]
    result = build_excerpts(events, max_excerpts=2)
    # Both kept; sorted chronologically with missing ts treated as 0
    assert result == ["no timestamp here", "has timestamp"]


def test_manual_entries_get_priority_prefix_and_survive_dedup_cap():
    """Manual-entry-sourced events MUST sort first regardless of length,
    survive the dedup cap, and carry the "用户原话：" prefix so the diary
    LLM's prompt-side instructions can find them."""
    events = [
        # Lots of long screen_time events that would otherwise win on length
        {"content": "really long screen activity title " * 5,
         "timestamp": 100.0, "source": "screen_time"},
        {"content": "another long screen activity title " * 4,
         "timestamp": 110.0, "source": "screen_time"},
        {"content": "yet another loooong screen entry " * 4,
         "timestamp": 120.0, "source": "screen_time"},
        # A short manual entry that should still be picked first
        {"content": "今天好累，想躺平",
         "timestamp": 130.0, "source": "manual_entry"},
    ]
    result = build_excerpts(events, max_excerpts=3)
    # Manual entry must be in the result and prefixed
    assert any(r.startswith("用户原话：今天好累") for r in result)


def test_nonmanual_sources_keep_their_exact_content_without_quote_tag():
    events = [
        {"content": "regular browser title", "timestamp": 1.0, "source": "chrome_history"},
        {
            "content": "用户原话 ish content but from chrome",
            "timestamp": 2.0,
            "source": "chrome_history",
        },
    ]
    assert build_excerpts(events, max_excerpts=2) == [
        "regular browser title",
        "用户原话 ish content but from chrome",
    ]
