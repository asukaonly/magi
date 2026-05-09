"""Tests for memory.recall_rendering shared utilities."""

from __future__ import annotations

import time

import pytest

from magi.memory.recall_rendering import (
    aggregate_by_statement,
    build_asset_manifest,
    format_date,
    format_relative,
    format_time_range,
    format_timestamp,
    is_echo_finding,
    truncate_statement,
)


class TestFormatTimestamp:
    def test_basic(self):
        ts = 1778064440.0  # 2026-05-06 06:54 UTC
        result = format_timestamp(ts)
        assert "2026-05-06" in result
        assert "Wed" in result

    def test_none(self):
        assert format_timestamp(None) == ""

    def test_invalid(self):
        assert format_timestamp(float("inf")) == ""


class TestFormatDate:
    def test_basic(self):
        assert format_date(1778064440.0) == "2026-05-06"

    def test_none(self):
        assert format_date(None) == ""


class TestFormatTimeRange:
    def test_same_day(self):
        result = format_time_range(1778064440.0, 1778064500.0)
        assert "~" not in result
        assert "2026-05-06" in result

    def test_different_days(self):
        start = 1778064440.0  # 2026-05-06
        end = start + 86400 * 3  # 3 days later
        result = format_time_range(start, end)
        assert "~" in result

    def test_none_start(self):
        result = format_time_range(None, 1778064440.0)
        assert "2026-05-06" in result

    def test_both_none(self):
        assert format_time_range(None, None) == ""


class TestFormatRelative:
    def test_minutes(self):
        now = time.time()
        result = format_relative(now - 300, now=now)
        assert "分钟前" in result

    def test_hours(self):
        now = time.time()
        result = format_relative(now - 7200, now=now)
        assert "小时前" in result

    def test_days(self):
        now = time.time()
        result = format_relative(now - 86400 * 5, now=now)
        assert "天前" in result

    def test_none(self):
        assert format_relative(None) == ""


class TestTruncateStatement:
    def test_short_text(self):
        text, truncated = truncate_statement("hello world", max_chars=200)
        assert text == "hello world"
        assert not truncated

    def test_long_text(self):
        text, truncated = truncate_statement("a " * 200, max_chars=50)
        assert len(text) <= 55
        assert truncated
        assert text.endswith("…")


class TestAggregateByStatement:
    def test_merge_duplicates(self):
        findings = [
            {"statement": "Visit A", "occurred_at": 100.0, "kind": "event"},
            {"statement": "Visit A", "occurred_at": 200.0, "kind": "event"},
            {"statement": "Visit A", "occurred_at": 300.0, "kind": "event"},
            {"statement": "Visit B", "occurred_at": 150.0, "kind": "event"},
        ]
        result = aggregate_by_statement(findings)
        assert len(result) == 2
        assert result[0]["statement"] == "Visit A"
        assert result[0]["count"] == 3
        assert result[0]["first_at"] == 100.0
        assert result[0]["last_at"] == 300.0
        assert result[1]["statement"] == "Visit B"
        assert result[1]["count"] == 1

    def test_empty(self):
        assert aggregate_by_statement([]) == []

    def test_preserves_order(self):
        findings = [
            {"statement": "B", "occurred_at": 1.0},
            {"statement": "A", "occurred_at": 2.0},
            {"statement": "B", "occurred_at": 3.0},
        ]
        result = aggregate_by_statement(findings)
        assert [r["statement"] for r in result] == ["B", "A"]

    def test_confidence_max(self):
        findings = [
            {"statement": "X", "occurred_at": 1.0, "confidence": 0.5},
            {"statement": "X", "occurred_at": 2.0, "confidence": 0.9},
        ]
        result = aggregate_by_statement(findings)
        assert result[0]["confidence"] == 0.9


class TestIsEchoFinding:
    def test_exact_match(self):
        assert is_echo_finding(
            {"kind": "event", "source_layer": "L1", "statement": "我喜欢什么音乐"},
            "我喜欢什么音乐",
        )

    def test_high_overlap(self):
        assert is_echo_finding(
            {"kind": "event", "source_layer": "L1", "statement": "我喜欢什么音乐呢"},
            "我喜欢什么音乐",
        )

    def test_not_echo_different_content(self):
        assert not is_echo_finding(
            {"kind": "event", "source_layer": "L1", "statement": "Chrome 浏览了某网站"},
            "我喜欢什么音乐",
        )

    def test_not_echo_l2(self):
        assert not is_echo_finding(
            {"kind": "relationship", "source_layer": "L2", "statement": "我喜欢什么音乐"},
            "我喜欢什么音乐",
        )

    def test_empty_query(self):
        assert not is_echo_finding(
            {"kind": "event", "source_layer": "L1", "statement": "hello"},
            "",
        )


class TestBuildAssetManifest:
    def test_aggregation(self):
        refs = [
            {"source_type": "chrome_history", "display_name": "Live A", "kind": "observation",
             "attributes": {"domain": "live.douyin.com"}},
            {"source_type": "chrome_history", "display_name": "Live A", "kind": "observation",
             "attributes": {"domain": "live.douyin.com"}},
            {"source_type": "chrome_history", "display_name": "Live B", "kind": "observation",
             "attributes": {"domain": "live.bilibili.com"}},
        ]
        result = build_asset_manifest(refs)
        assert len(result) == 2
        assert result[0]["display_name"] == "Live A"
        assert result[0]["count"] == 2
        assert result[0]["domain"] == "live.douyin.com"
        assert result[1]["count"] == 1

    def test_empty(self):
        assert build_asset_manifest([]) == []

    def test_missing_display_name(self):
        refs = [{"source_type": "x", "kind": "observation"}]
        assert build_asset_manifest(refs) == []
