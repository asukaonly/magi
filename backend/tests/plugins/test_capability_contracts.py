import pytest

from magi.plugins.contracts import (
    PluginCapability,
    PluginManifest,
    PluginRegistryEntry,
)


@pytest.mark.parametrize("owner", ["capability", "manifest", "registry"])
def test_capability_wire_contract_preserves_scope_and_localized_consent(owner):
    capability = {
        "capability": "filesystem_read",
        "scope": ["~/Library/Calendars"],
        "optional": True,
        "reason": "Read selected calendars",
        "reason_i18n": {"en": "read cal", "zh-CN": "读日历"},
    }
    if owner == "capability":
        model = PluginCapability.model_validate(capability)
        assert model.model_dump(mode="json") == capability
    elif owner == "manifest":
        model = PluginManifest.model_validate(
            {
                "id": "example",
                "name": "Example",
                "version": "1.0.0",
                "permissions": {"capabilities": [capability]},
            }
        )
        assert [item.model_dump(mode="json") for item in model.capabilities] == [capability]
        assert model.model_dump(mode="json")["permissions"] == {"capabilities": [capability]}
    else:
        model = PluginRegistryEntry.model_validate(
            {
                "plugin_id": "example",
                "name": "Example",
                "version": "1.0.0",
                "package_sha256": "a" * 64,
                "capabilities": [capability],
            }
        )
        assert model.model_dump(mode="json")["capabilities"] == [capability]
    assert type(model).model_validate(model.model_dump(mode="json")) == model


def test_unknown_capability_string_still_parses():
    # Forward-compat: wire model is permissive str, not Literal.
    c = PluginCapability.model_validate({"capability": "future_thing"})
    assert c.capability == "future_thing"


def test_manifest_rejects_removed_permission_fields():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="Extra inputs"):
        PluginManifest.model_validate({
            "id": "legacy", "name": "Legacy", "version": "1.0.0",
            "permissions": {"declares": ["legacy"], "memory_access": ["write_l1"]},
        })
