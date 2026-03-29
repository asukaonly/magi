"""Tests for Chrome history normalizer helpers — title parsing and entity extraction."""
from __future__ import annotations

import pytest

from normalizers import (
    parse_title_entities,
    _match_platform_suffix,
)


class TestMatchPlatformSuffix:
    def test_known_en_platform(self):
        assert _match_platform_suffix("YouTube") == "YouTube"

    def test_known_cn_platform(self):
        assert _match_platform_suffix("哔哩哔哩") == "Bilibili"

    def test_bilibili_composite_suffix(self):
        assert _match_platform_suffix("哔哩哔哩_bilibili") == "Bilibili"

    def test_unknown_segment(self):
        assert _match_platform_suffix("RandomSite") is None

    def test_empty_string(self):
        assert _match_platform_suffix("") is None

    def test_google_search(self):
        assert _match_platform_suffix("Google Search") == "Google"

    def test_github(self):
        assert _match_platform_suffix("GitHub") == "GitHub"


class TestParseTitleEntities:
    def test_content_dash_platform(self):
        hints = parse_title_entities("Radiohead | Last.fm", "last.fm")
        names = {h["canonical_name_hint"] for h in hints}
        types = {h["entity_type"] for h in hints}
        assert "Last.fm" in names
        assert "Radiohead" in names
        assert "software" in types
        assert "media" in types

    def test_bilibili_title(self):
        hints = parse_title_entities(
            "新鲜哥 - 哔哩哔哩_bilibili", "bilibili.com",
        )
        platforms = [h for h in hints if h["entity_type"] == "software"]
        assert any(h["canonical_name_hint"] == "Bilibili" for h in platforms)
        media = [h for h in hints if h["entity_type"] == "media"]
        assert any(h["canonical_name_hint"] == "新鲜哥" for h in media)

    def test_douyin_title(self):
        hints = parse_title_entities(
            "坤的真爱粉的抖音直播间 - 抖音", "douyin.com",
        )
        platforms = [h for h in hints if h["entity_type"] == "software"]
        assert any(h["canonical_name_hint"] == "Douyin" for h in platforms)
        media = [h for h in hints if h["entity_type"] == "media"]
        assert any("坤" in h["canonical_name_hint"] for h in media)

    def test_github_title(self):
        hints = parse_title_entities(
            "openai/openai-python - GitHub", "github.com",
        )
        platforms = [h for h in hints if h["entity_type"] == "software"]
        assert any(h["canonical_name_hint"] == "GitHub" for h in platforms)

    def test_google_search_title(self):
        hints = parse_title_entities(
            "野犬 说法 - Google Search", "google.com",
        )
        platforms = [h for h in hints if h["entity_type"] == "software"]
        assert any(h["canonical_name_hint"] == "Google" for h in platforms)

    def test_no_separator_uses_domain(self):
        hints = parse_title_entities("GitHub", "github.com")
        assert len(hints) >= 1
        assert any(h["entity_type"] == "software" and h["canonical_name_hint"] == "GitHub" for h in hints)

    def test_empty_title(self):
        assert parse_title_entities("", "example.com") == []

    def test_unknown_domain_no_separator(self):
        hints = parse_title_entities("Some Random Page", "example.com")
        assert hints == []

    def test_short_content_part_filtered(self):
        """Content part with only one char should not produce a media hint."""
        hints = parse_title_entities("X - YouTube", "youtube.com")
        media = [h for h in hints if h["entity_type"] == "media"]
        assert len(media) == 0
