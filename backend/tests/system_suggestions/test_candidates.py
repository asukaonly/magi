from types import SimpleNamespace
from magi.system_suggestions.candidates import build_suggestion_candidates, SuggestionCandidate


def _desc(category):
    return SimpleNamespace(category=category)


def _manifest(pid, desc):
    return SimpleNamespace(plugin_id=pid, suggestion_descriptor=desc)


def _entry(pid, desc):
    return SimpleNamespace(plugin_id=pid, suggestion_descriptor=desc)


def test_union_tags_installed_and_dedups():
    installed = [_manifest("chrome-history", _desc("browser_history")),
                 _manifest("no-desc", None)]
    registry = [_entry("chrome-history", _desc("browser_history")),  # dup -> installed wins
                _entry("git-activity", _desc("code_activity")),      # registry-only
                _entry("lib-only", None)]                            # no descriptor -> skip
    cands = build_suggestion_candidates(installed, registry)
    by_id = {c.plugin_id: c for c in cands}
    assert set(by_id) == {"chrome-history", "git-activity"}
    assert by_id["chrome-history"].installed is True
    assert by_id["git-activity"].installed is False


def test_empty_inputs():
    assert build_suggestion_candidates([], []) == []
