import json

import pytest
from pydantic import ValidationError

from magi.plugins.contracts import (
    PluginManifest,
    PluginRegistryEntry,
    PluginRegistryIndex,
)

PACKAGE_SHA256 = "a" * 64


def test_registry_index_requires_current_contract_version():
    assert PluginRegistryIndex(registry_version="4").registry_version == "4"

    with pytest.raises(ValidationError):
        PluginRegistryIndex(registry_version="3")
    with pytest.raises(ValidationError):
        PluginRegistryIndex()


@pytest.mark.parametrize(
    "icon,icon_data,display_icon",
    [
        (
            "asset:assets/icon.svg",
            "data:image/svg+xml;base64,PHN2Zy8+",
            "data:image/svg+xml;base64,PHN2Zy8+",
        ),
        ("lucide:globe", "", "lucide:globe"),
        ("", "", ""),
    ],
)
def test_manifest_and_registry_preserve_public_metadata_on_json_roundtrip(
    icon, icon_data, display_icon
):
    shared = {
        "name": "Browser History",
        "version": "0.1.0",
        "data_locality": "local_only",
        "icon": icon,
        "display_group": {
            "id": "browser_history",
            "name": "Browser History",
            "name_i18n": {"zh-CN": "浏览器历史"},
            "description": "Manage browser history sources.",
            "description_i18n": {"zh-CN": "统一管理浏览器历史入口。"},
            "icon": "lucide:globe",
            "member_label": "Brave",
            "member_label_i18n": {"zh-CN": "Brave 浏览器"},
            "order": 20,
            "member_order": 50,
        },
        "suggestion_descriptor": {
            "category": "browser_history",
            "triggers": {"keywords": {"zh": ["浏览"], "en": ["browsing"]}},
            "platform_support": ["darwin", "win32"],
            "rationale": {"zh": "读取浏览器历史", "en": "read browser history"},
        },
    }
    manifest = PluginManifest.model_validate({"id": "brave-history", **shared})
    entry = PluginRegistryEntry.model_validate(
        {
            "plugin_id": "brave-history",
            "path": "plugins/brave-history",
            "platforms": ["macos", "windows"],
            "package_sha256": PACKAGE_SHA256,
            "icon_data": icon_data,
            **shared,
        }
    )
    for model in [manifest, entry]:
        encoded = model.model_dump_json(by_alias=True)
        wire = json.loads(encoded)
        assert wire["data_locality"] == "local_only"
        assert wire["icon"] == icon
        assert wire["display_group"] == shared["display_group"]
        descriptor = wire["suggestion_descriptor"]
        for key, value in shared["suggestion_descriptor"].items():
            if key == "triggers":
                assert descriptor[key]["keywords"] == value["keywords"]
            else:
                assert descriptor[key] == value
        assert type(model).model_validate_json(encoded) == model
    assert entry.display_icon == display_icon
    assert json.loads(manifest.model_dump_json(by_alias=True))["id"] == "brave-history"
    wire = json.loads(entry.model_dump_json())
    assert (wire["plugin_id"], wire["package_sha256"], wire["icon_data"]) == (
        "brave-history",
        PACKAGE_SHA256,
        icon_data,
    )
