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


def _pkg(pid, desc, enabled):
    return SimpleNamespace(manifest=_manifest(pid, desc), enabled=enabled)


def test_partition_excludes_enabled_installed_plugins():
    from magi.system_suggestions.candidates import partition_for_candidates

    packages = [
        _pkg("chrome-history", _desc("browser_history"), enabled=True),   # active -> drop
        _pkg("git-activity", _desc("code_activity"), enabled=False),      # inactive -> connect
    ]
    registry = [
        _entry("chrome-history", _desc("browser_history")),  # installed (active) -> NOT re-suggested
        _entry("edge-history", _desc("browser_history")),    # not installed -> install
    ]
    installed_manifests, registry_entries = partition_for_candidates(packages, registry)
    cands = build_suggestion_candidates(installed_manifests, registry_entries)
    by_id = {c.plugin_id: c for c in cands}
    # chrome-history is installed+enabled -> excluded entirely (not as connect, not as install)
    assert "chrome-history" not in by_id
    assert by_id["git-activity"].installed is True       # installed but inactive -> connect
    assert by_id["edge-history"].installed is False       # not installed -> install
