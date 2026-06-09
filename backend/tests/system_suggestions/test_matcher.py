"""Tests for the signal matcher: candidate_categories + build_proposals."""

from __future__ import annotations

from types import SimpleNamespace

from magi.system_suggestions.matcher import (
    CategoryCandidate,
    build_proposals,
    candidate_categories,
)


def _cand(
    pid: str, category: str, kw: list[str], installed: bool
) -> SimpleNamespace:
    """Build a SuggestionCandidate-shaped object (zh keywords only)."""
    desc = SimpleNamespace(
        category=category,
        triggers=SimpleNamespace(keywords={"zh": kw, "en": []}),
        rationale=SimpleNamespace(zh="z", en="e"),
    )
    return SimpleNamespace(plugin_id=pid, descriptor=desc, installed=installed)


def test_candidate_categories_groups_keyword_hits_by_category() -> None:
    cands = [
        _cand("chrome-history", "browser_history", ["浏览", "网页"], True),
        _cand("edge-history", "browser_history", ["浏览"], True),
        _cand("git-activity", "code_activity", ["代码"], True),
    ]
    grouped = candidate_categories(
        recent_text="我上周浏览了哪些网页",
        locale="zh",
        candidates=cands,
        is_available=lambda _pid: True,
        is_dismissed=lambda _cat: False,
    )
    assert set(grouped.keys()) == {"browser_history"}
    assert sorted(grouped["browser_history"].plugin_ids) == [
        "chrome-history",
        "edge-history",
    ]


def test_candidate_categories_tracks_installable() -> None:
    cands = [
        _cand("chrome-history", "browser_history", ["浏览"], True),
        _cand("edge-history", "browser_history", ["浏览"], False),
    ]
    grouped = candidate_categories(
        recent_text="浏览",
        locale="zh",
        candidates=cands,
        is_available=lambda _pid: True,
        is_dismissed=lambda _c: False,
    )
    cat = grouped["browser_history"]
    assert sorted(cat.plugin_ids) == ["chrome-history", "edge-history"]
    assert cat.installable_plugin_ids == ["edge-history"]


def test_candidate_categories_filters_unavailable_and_dismissed() -> None:
    cands = [_cand("chrome-history", "browser_history", ["浏览"], True)]
    assert (
        candidate_categories(
            recent_text="浏览",
            locale="zh",
            candidates=cands,
            is_available=lambda _pid: False,
            is_dismissed=lambda _c: False,
        )
        == {}
    )
    assert (
        candidate_categories(
            recent_text="浏览",
            locale="zh",
            candidates=cands,
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


def test_build_proposals_carries_installable() -> None:
    cands = {
        "browser_history": CategoryCandidate(
            category="browser_history",
            plugin_ids=["chrome-history", "edge-history"],
            installable_plugin_ids=["edge-history"],
            keywords=["浏览"],
            rationale={"zh": "z", "en": "e"},
            keyword_hits=1,
        )
    }
    props = build_proposals(cands, confidences=None)
    assert props[0].installable_plugin_ids == ["edge-history"]
