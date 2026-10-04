"""Tests for memory.recall_rendering shared utilities."""

from __future__ import annotations

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
    @pytest.mark.parametrize(
        "timestamp,offset,expected_stamp,expected_date",
        [
            (0, 0, "1970-01-01 Thu 00:00", "1970-01-01"),
            (0, -8, "1969-12-31 Wed 16:00", "1969-12-31"),
            (84600, 8, "1970-01-02 Fri 07:30", "1970-01-02"),
            (None, 0, "", ""),
            (float("inf"), 0, "", ""),
            (float("nan"), 0, "", ""),
        ],
    )
    def test_timestamps_render_exact_local_calendar_values(
        self, monkeypatch, timestamp, offset, expected_stamp, expected_date
    ):
        from datetime import timedelta, timezone
        from magi.memory import recall_rendering

        monkeypatch.setattr(recall_rendering, "_local_tz", lambda: timezone(timedelta(hours=offset)))
        assert format_timestamp(timestamp) == expected_stamp
        assert format_date(timestamp) == expected_date


class TestFormatTimeRange:
    @pytest.mark.parametrize(
        "start,end,expected",
        [
            (0, 3600, "1970-01-01"),
            (0, 259200, "1970-01-01 ~ 1970-01-04"),
            (None, 86400, "1970-01-02"),
            (86400, None, "1970-01-02"),
            (None, None, ""),
        ],
    )
    def test_date_ranges_preserve_both_endpoints(self, monkeypatch, start, end, expected):
        from datetime import timezone
        from magi.memory import recall_rendering

        monkeypatch.setattr(recall_rendering, "_local_tz", lambda: timezone.utc)
        assert format_time_range(start, end) == expected


class TestFormatRelative:
    @pytest.mark.parametrize(
        "elapsed,expected",
        [
            (None, ""),
            (-1, ""),
            (0, "1 分钟前"),
            (59, "1 分钟前"),
            (60, "1 分钟前"),
            (119, "1 分钟前"),
            (120, "2 分钟前"),
            (300, "5 分钟前"),
            (3599, "59 分钟前"),
            (3600, "1 小时前"),
            (7200, "2 小时前"),
            (86399, "23 小时前"),
            (86400, "1 天前"),
            (432000, "5 天前"),
            (2592000, "30 天前"),
            (2678400, "1 个月前"),
            (31104000, "12 个月前"),
            (33696000, "1970-01-11"),
        ],
    )
    def test_relative_time_uses_exact_values_at_unit_boundaries(self, monkeypatch, elapsed, expected):
        from datetime import timezone
        from magi.memory import recall_rendering

        monkeypatch.setattr(recall_rendering, "_local_tz", lambda: timezone.utc)
        now = 34560000.0
        timestamp = None if elapsed is None else now - elapsed
        assert format_relative(timestamp, now=now) == expected


class TestTruncateStatement:
    @pytest.mark.parametrize(
        "text,budget,expected",
        [
            ("  hello world  ", 11, ("hello world", False)),
            ("", 3, ("", False)),
            ("alpha beta gamma delta", 12, ("alpha beta…", True)),
            ("春夏秋冬风花雪月", 6, ("春夏秋冬风花…", True)),
        ],
    )
    def test_truncation_keeps_exact_prefix_and_marks_only_clipped_text(self, text, budget, expected):
        assert truncate_statement(text, max_chars=budget) == expected


class TestAggregateByStatement:
    @pytest.mark.parametrize("empty", [False, True], ids=["mixed-findings", "empty"])
    def test_aggregation_preserves_first_seen_order_time_extents_and_peak_confidence(self, empty):
        from copy import deepcopy

        findings = (
            []
            if empty
            else [
                {"statement": "B", "occurred_at": 150.0, "kind": "event", "confidence": 0.7},
                {"statement": "A", "occurred_at": 200.0, "kind": "event", "confidence": 0.5},
                {"statement": "A", "occurred_at": 100.0, "kind": "event", "confidence": 0.9},
                {"statement": "A", "occurred_at": 300.0, "kind": "event", "confidence": 0.6},
            ]
        )
        before = deepcopy(findings)
        result = aggregate_by_statement(findings)
        assert [
            (row["statement"], row["count"], row["first_at"], row["last_at"], row["confidence"])
            for row in result
        ] == ([] if empty else [("B", 1, 150.0, 150.0, 0.7), ("A", 3, 100.0, 300.0, 0.9)])
        assert findings == before


class TestIsEchoFinding:
    @pytest.mark.parametrize(
        "case_finding_text",
        [
            pytest.param("我喜欢什么音乐", id="exact_match"),
            pytest.param("我喜欢什么音乐呢", id="high_overlap"),
        ],
    )
    def test_query_echo_detection_handles_exact_and_high_overlap(self, case_finding_text):
        assert is_echo_finding(
            {"kind": "event", "source_layer": "L1", "statement": case_finding_text}, "我喜欢什么音乐"
        )


    @pytest.mark.parametrize(
        "case_query,case_finding_kind,case_layer,case_finding_text",
        [
            pytest.param(
                "我喜欢什么音乐", "event", "L1", "Chrome 浏览了某网站", id="not_echo_different_content"
            ),
            pytest.param("我喜欢什么音乐", "relationship", "L2", "我喜欢什么音乐", id="not_echo_l2"),
            pytest.param("", "event", "L1", "hello", id="empty_query"),
        ],
    )
    def test_non_echo_findings_preserve_layer_and_query_distinctions(
        self, case_query, case_finding_kind, case_layer, case_finding_text
    ):
        assert not is_echo_finding(
            {"kind": case_finding_kind, "source_layer": case_layer, "statement": case_finding_text},
            case_query,
        )


class TestBuildAssetManifest:
    @pytest.mark.parametrize("case", ["mixed", "empty", "missing-name"])
    def test_asset_manifest_groups_by_source_and_name_and_exposes_only_summary_fields(self, case):
        refs = [] if case == "empty" else [{"source_type": "x", "kind": "observation"}]
        if case == "mixed":
            refs = [
                {
                    "source_type": "chrome_history",
                    "display_name": "Live A",
                    "kind": "observation",
                    "attributes": {"domain": "live.douyin.com", "unrelated_detail": "private"},
                },
                {
                    "source_type": "chrome_history",
                    "display_name": "Live A",
                    "kind": "observation",
                    "attributes": {"domain": "live.douyin.com"},
                },
                {
                    "source_type": "chrome_history",
                    "display_name": "Live B",
                    "kind": "observation",
                    "attributes": {"domain": "live.bilibili.com"},
                },
                {"source_type": "other", "display_name": "Live A", "kind": "observation"},
            ]
        assert build_asset_manifest(refs) == (
            []
            if case != "mixed"
            else [
                {
                    "source_type": "chrome_history",
                    "display_name": "Live A",
                    "kind": "observation",
                    "domain": "live.douyin.com",
                    "count": 2,
                },
                {
                    "source_type": "chrome_history",
                    "display_name": "Live B",
                    "kind": "observation",
                    "domain": "live.bilibili.com",
                    "count": 1,
                },
                {
                    "source_type": "other",
                    "display_name": "Live A",
                    "kind": "observation",
                    "domain": "",
                    "count": 1,
                },
            ]
        )
