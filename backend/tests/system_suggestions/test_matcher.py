"""Tests for find_suggestions — the signal matcher."""

from __future__ import annotations

from magi.system_suggestions.matcher import find_suggestions
from magi_plugin_sdk.contracts import PluginManifest


def test_keyword_match_in_locale_fires_a_suggestion(make_manifest_fixture) -> None:
    manifests = [
        make_manifest_fixture(
            "chrome-history",
            category="browser_history",
            keywords={"zh": ["浏览", "网页"], "en": ["browsing", "website"]},
        ),
    ]
    suggestions = find_suggestions(
        recent_text="我上周看了什么浏览",
        locale="zh",
        plugin_manifests=manifests,
        is_available=lambda _: True,
        is_dismissed=lambda _: False,
    )
    assert len(suggestions) == 1
    assert suggestions[0].plugin_ids == ["chrome-history"]
    assert suggestions[0].category == "browser_history"


def test_no_keyword_match_no_suggestion(make_manifest_fixture) -> None:
    manifests = [
        make_manifest_fixture(
            "chrome-history",
            category="browser_history",
            keywords={"zh": ["浏览"], "en": ["browsing"]},
        ),
    ]
    suggestions = find_suggestions(
        recent_text="random unrelated text",
        locale="zh",
        plugin_manifests=manifests,
        is_available=lambda _: True,
        is_dismissed=lambda _: False,
    )
    assert suggestions == []


def test_unavailable_plugin_filtered_out(make_manifest_fixture) -> None:
    manifests = [
        make_manifest_fixture(
            "chrome-history",
            category="browser_history",
            keywords={"zh": ["浏览"], "en": ["browsing"]},
        ),
    ]
    suggestions = find_suggestions(
        recent_text="我看了什么浏览",
        locale="zh",
        plugin_manifests=manifests,
        is_available=lambda _: False,
        is_dismissed=lambda _: False,
    )
    assert suggestions == []


def test_dismissed_category_filtered_out(make_manifest_fixture) -> None:
    manifests = [
        make_manifest_fixture(
            "chrome-history",
            category="browser_history",
            keywords={"zh": ["浏览"], "en": ["browsing"]},
        ),
    ]
    suggestions = find_suggestions(
        recent_text="我看了什么浏览",
        locale="zh",
        plugin_manifests=manifests,
        is_available=lambda _: True,
        is_dismissed=lambda key: key == "browser_history",
    )
    assert suggestions == []


def test_sibling_plugins_bundle_into_one_suggestion(make_manifest_fixture) -> None:
    manifests = [
        make_manifest_fixture(
            "chrome-history",
            category="browser_history",
            keywords={"zh": ["浏览"], "en": ["browsing"]},
        ),
        make_manifest_fixture(
            "safari-history",
            category="browser_history",
            keywords={"zh": ["浏览"], "en": ["browsing"]},
        ),
    ]
    suggestions = find_suggestions(
        recent_text="我看了什么浏览",
        locale="zh",
        plugin_manifests=manifests,
        is_available=lambda _: True,
        is_dismissed=lambda _: False,
    )
    assert len(suggestions) == 1
    assert set(suggestions[0].plugin_ids) == {"chrome-history", "safari-history"}
    assert suggestions[0].category == "browser_history"


def test_different_categories_emit_separate_suggestions(make_manifest_fixture) -> None:
    manifests = [
        make_manifest_fixture(
            "chrome-history",
            category="browser_history",
            keywords={"zh": ["浏览"], "en": ["browsing"]},
        ),
        make_manifest_fixture(
            "git-activity",
            category="code_activity",
            keywords={"zh": ["代码"], "en": ["code"]},
        ),
    ]
    suggestions = find_suggestions(
        recent_text="我看了什么浏览以及我的代码",
        locale="zh",
        plugin_manifests=manifests,
        is_available=lambda _: True,
        is_dismissed=lambda _: False,
    )
    assert len(suggestions) == 2
    categories = {s.category for s in suggestions}
    assert categories == {"browser_history", "code_activity"}


def test_plugin_without_descriptor_skipped() -> None:
    manifests = [
        PluginManifest(
            id="legacy", name="Legacy", version="0.1.0",
            entry_module="plugin", entry_class="X",
        ),
    ]
    suggestions = find_suggestions(
        recent_text="anything",
        locale="zh",
        plugin_manifests=manifests,
        is_available=lambda _: True,
        is_dismissed=lambda _: False,
    )
    assert suggestions == []


def test_locale_filtering_only_matches_requested_locale(make_manifest_fixture) -> None:
    manifests = [
        make_manifest_fixture(
            "chrome-history",
            category="browser_history",
            keywords={"zh": ["浏览"], "en": ["browsing"]},
        ),
    ]
    suggestions = find_suggestions(
        recent_text="hey did you check my browsing",
        locale="zh",
        plugin_manifests=manifests,
        is_available=lambda _: True,
        is_dismissed=lambda _: False,
    )
    assert suggestions == []
    suggestions = find_suggestions(
        recent_text="hey did you check my browsing",
        locale="en",
        plugin_manifests=manifests,
        is_available=lambda _: True,
        is_dismissed=lambda _: False,
    )
    assert len(suggestions) == 1


def test_unsupported_platform_filters_plugin(make_manifest_fixture) -> None:
    manifests = [
        make_manifest_fixture(
            "chrome-history",
            category="browser_history",
            keywords={"zh": ["浏览"], "en": ["browsing"]},
            platforms=["linux"],
        ),
    ]
    suggestions = find_suggestions(
        recent_text="浏览",
        locale="zh",
        plugin_manifests=manifests,
        is_available=lambda _: False,
        is_dismissed=lambda _: False,
    )
    assert suggestions == []
