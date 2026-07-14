from types import SimpleNamespace
from magi.system_suggestions.candidates import build_suggestion_candidates, SuggestionCandidate


def _desc(category):
    return SimpleNamespace(category=category, icon=None)


def _manifest(pid, desc):
    return SimpleNamespace(
        plugin_id=pid,
        name=pid,
        name_i18n={"zh-CN": f"{pid} 中文"},
        description=f"{pid} description",
        description_i18n={},
        icon="lucide:activity",
        suggestion_descriptor=desc,
    )


def _entry(pid, desc):
    return _manifest(pid, desc)


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
    assert by_id["git-activity"].name == "git-activity"
    assert by_id["git-activity"].icon == "lucide:activity"


def test_empty_inputs():
    assert build_suggestion_candidates([], []) == []


def _pkg(pid, desc):
    return SimpleNamespace(manifest=_manifest(pid, desc))


def test_partition_excludes_active_source_categories():
    from magi.system_suggestions.candidates import partition_for_candidates

    packages = [
        _pkg("chrome-history", _desc("browser_history")),  # source in-use -> drop
        _pkg("git-activity", _desc("code_activity")),      # installed, source off -> connect
    ]
    registry = [
        _entry("chrome-history", _desc("browser_history")),  # active -> NOT re-suggested
        _entry("edge-history", _desc("browser_history")),    # active sibling category -> drop
    ]
    # chrome-history has an enabled+configured sensor source (in use).
    active = {"chrome-history"}
    installed_manifests, registry_entries = partition_for_candidates(
        packages, registry, active
    )
    cands = build_suggestion_candidates(installed_manifests, registry_entries)
    by_id = {c.plugin_id: c for c in cands}
    # The active browser category is excluded entirely, including sibling browsers.
    assert "chrome-history" not in by_id
    assert by_id["git-activity"].installed is True       # installed but source off -> connect
    assert "edge-history" not in by_id


def test_partition_without_active_set_keeps_all_installed_as_connect():
    from magi.system_suggestions.candidates import partition_for_candidates

    packages = [_pkg("chrome-history", _desc("browser_history"))]
    installed_manifests, _ = partition_for_candidates(packages, [])
    cands = build_suggestion_candidates(installed_manifests, [])
    assert {c.plugin_id for c in cands} == {"chrome-history"}
