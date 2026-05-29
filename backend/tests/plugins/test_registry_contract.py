from magi.plugins.contracts import PluginRegistryEntry


def test_registry_entry_parses_suggestion_descriptor():
    entry = PluginRegistryEntry.model_validate({
        "plugin_id": "chrome-history", "name": "Chrome History", "version": "0.1.0",
        "path": "plugins/chrome-history", "platforms": ["macos", "windows"],
        "suggestion_descriptor": {
            "category": "browser_history",
            "triggers": {"keywords": {"zh": ["浏览"], "en": ["browsing"]}},
            "platform_support": ["darwin", "win32"],
            "rationale": {"zh": "读取浏览历史", "en": "read browser history"},
        },
    })
    assert entry.suggestion_descriptor is not None
    assert entry.suggestion_descriptor.category == "browser_history"


def test_registry_entry_without_descriptor_is_none():
    entry = PluginRegistryEntry.model_validate({
        "plugin_id": "x", "name": "X", "version": "0.1.0", "path": "plugins/x", "platforms": [],
    })
    assert entry.suggestion_descriptor is None
