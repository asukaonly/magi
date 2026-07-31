from magi.plugins.contracts import (
    PluginCapability,
    PluginManifest,
    PluginRegistryEntry,
)


def test_capability_parses_all_fields():
    c = PluginCapability.model_validate(
        {
            "capability": "filesystem_read",
            "scope": ["~/Library/Calendars"],
            "optional": True,
            "reason_i18n": {"en": "read cal", "zh-CN": "读日历"},
        }
    )
    assert c.capability == "filesystem_read"
    assert c.scope == ["~/Library/Calendars"]
    assert c.optional is True
    assert c.reason_i18n["zh-CN"] == "读日历"


def test_capability_defaults():
    c = PluginCapability.model_validate({"capability": "network"})
    assert c.scope == []
    assert c.optional is False
    assert c.reason == ""


def test_unknown_capability_string_still_parses():
    # Forward-compat: wire model is permissive str, not Literal.
    c = PluginCapability.model_validate({"capability": "future_thing"})
    assert c.capability == "future_thing"


def test_manifest_reads_permissions_capabilities():
    m = PluginManifest.model_validate(
        {
            "id": "x",
            "name": "X",
            "version": "1.0.0",
            "permissions": {
                "capabilities": [{"capability": "network", "scope": ["a.com"]}],
                "declares": ["legacy"],  # legacy key tolerated
                "memory_access": ["write_l1"],  # legacy key tolerated
            },
        }
    )
    assert [c.capability for c in m.capabilities] == ["network"]


def test_manifest_without_permissions_has_empty_capabilities():
    m = PluginManifest.model_validate({"id": "y", "name": "Y", "version": "1.0.0"})
    assert m.capabilities == []


def test_registry_entry_top_level_capabilities():
    e = PluginRegistryEntry.model_validate(
        {
            "plugin_id": "x",
            "name": "X",
            "version": "1.0.0",
            "package_sha256": "a" * 64,
            "capabilities": [{"capability": "calendar"}],
        }
    )
    assert e.capabilities[0].capability == "calendar"
