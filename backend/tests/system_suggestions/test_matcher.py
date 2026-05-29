"""Tests for the signal matcher: candidate_categories + build_proposals."""

from __future__ import annotations

from magi.system_suggestions.matcher import (
    CategoryCandidate,
    build_proposals,
    candidate_categories,
)
from magi_plugin_sdk.contracts import (
    LocalizedText,
    PluginManifest,
    SuggestionDescriptor,
    Triggers,
)


def _manifest(
    plugin_id: str, category: str, keywords_zh: list[str]
) -> PluginManifest:
    """Build a PluginManifest with a suggestion_descriptor (zh keywords only)."""
    return PluginManifest(
        id=plugin_id,
        name=plugin_id,
        version="0.1.0",
        entry_module="plugin",
        entry_class="X",
        suggestion_descriptor=SuggestionDescriptor(
            category=category,
            triggers=Triggers(
                intents=[],
                entities=[],
                keywords={"zh": keywords_zh},
            ),
            platform_support=["darwin", "win32", "linux"],
            local_requirements=[],
            rationale=LocalizedText(
                zh=f"connect {plugin_id} (zh)",
                en=f"connect {plugin_id} (en)",
            ),
        ),
    )


def test_candidate_categories_groups_keyword_hits_by_category() -> None:
    manifests = [
        _manifest("chrome-history", "browser_history", ["浏览", "网页"]),
        _manifest("edge-history", "browser_history", ["浏览"]),
        _manifest("git-activity", "code_activity", ["代码"]),
    ]
    cands = candidate_categories(
        recent_text="我上周浏览了哪些网页",
        locale="zh",
        plugin_manifests=manifests,
        is_available=lambda _pid: True,
        is_dismissed=lambda _cat: False,
    )
    assert set(cands.keys()) == {"browser_history"}
    assert sorted(cands["browser_history"].plugin_ids) == [
        "chrome-history",
        "edge-history",
    ]


def test_candidate_categories_filters_unavailable_and_dismissed() -> None:
    manifests = [_manifest("chrome-history", "browser_history", ["浏览"])]
    assert (
        candidate_categories(
            recent_text="浏览",
            locale="zh",
            plugin_manifests=manifests,
            is_available=lambda _pid: False,
            is_dismissed=lambda _c: False,
        )
        == {}
    )
    assert (
        candidate_categories(
            recent_text="浏览",
            locale="zh",
            plugin_manifests=manifests,
            is_available=lambda _pid: True,
            is_dismissed=lambda _c: True,
        )
        == {}
    )


def _cands() -> dict[str, CategoryCandidate]:
    return {
        "browser_history": CategoryCandidate(
            category="browser_history",
            plugin_ids=["chrome-history"],
            keywords=["浏览"],
            rationale={"zh": "z", "en": "e"},
            keyword_hits=2,
        ),
        "code_activity": CategoryCandidate(
            category="code_activity",
            plugin_ids=["git-activity"],
            keywords=["代码"],
            rationale={"zh": "z", "en": "e"},
            keyword_hits=1,
        ),
    }


def test_build_proposals_uses_llm_confidences_and_drops_zero() -> None:
    props = build_proposals(
        _cands(), confidences={"browser_history": 0.9, "code_activity": 0.0}
    )
    assert [p.category for p in props] == ["browser_history"]
    assert props[0].confidence == 0.9
    assert props[0].plugin_ids == ["chrome-history"]


def test_build_proposals_degrades_to_keyword_when_confidences_none() -> None:
    props = build_proposals(_cands(), confidences=None)
    assert {p.category for p in props} == {"browser_history", "code_activity"}
    assert props[0].category == "browser_history"  # more hits -> higher keyword confidence
