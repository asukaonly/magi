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


def test_registry_entry_parses_data_locality():
    # Privacy-transparency signal (data-locality badge): declared per plugin.
    entry = PluginRegistryEntry.model_validate(
        {
            "plugin_id": "screenshot_timeline",
            "name": "Screenshot Timeline",
            "version": "0.1.0",
            "path": "plugins/screenshot_timeline",
            "platforms": ["macos"],
            "package_sha256": PACKAGE_SHA256,
            "data_locality": "local_only",
        }
    )
    assert entry.data_locality == "local_only"


def test_registry_entry_data_locality_defaults_empty():
    entry = PluginRegistryEntry.model_validate(
        {
            "plugin_id": "x",
            "name": "X",
            "version": "0.1.0",
            "path": "plugins/x",
            "platforms": [],
            "package_sha256": PACKAGE_SHA256,
        }
    )
    assert entry.data_locality == ""


def test_manifest_parses_data_locality():
    manifest = PluginManifest.model_validate(
        {
            "id": "screenshot_timeline",
            "name": "Screenshot Timeline",
            "version": "0.1.0",
            "data_locality": "local_only",
        }
    )
    assert manifest.data_locality == "local_only"


def test_manifest_and_registry_entry_parse_plugin_owned_icon():
    icon_data = "data:image/svg+xml;base64,PHN2Zy8+"
    manifest = PluginManifest.model_validate(
        {
            "id": "chrome-history",
            "name": "Chrome History",
            "version": "0.1.0",
            "icon": "asset:assets/icon.svg",
        }
    )
    entry = PluginRegistryEntry.model_validate(
        {
            "plugin_id": "chrome-history",
            "name": "Chrome History",
            "version": "0.1.0",
            "path": "plugins/chrome-history",
            "platforms": ["macos"],
            "package_sha256": PACKAGE_SHA256,
            "icon": "asset:assets/icon.svg",
            "icon_data": icon_data,
        }
    )

    assert manifest.icon == "asset:assets/icon.svg"
    assert entry.icon == "asset:assets/icon.svg"
    assert entry.display_icon == icon_data


def test_manifest_and_registry_entry_parse_display_group():
    manifest = PluginManifest.model_validate(
        {
            "id": "brave-history",
            "name": "Brave History",
            "version": "0.1.0",
            "display_group": {
                "id": "browser_history",
                "name": "Browser History",
                "name_i18n": {"zh-CN": "浏览器历史"},
                "description": "Manage browser history sources.",
                "description_i18n": {"zh-CN": "统一管理浏览器历史入口。"},
                "icon": "lucide:globe",
                "member_label": "Brave",
                "member_order": 50,
            },
        }
    )
    entry = PluginRegistryEntry.model_validate(
        {
            "plugin_id": "brave-history",
            "name": "Brave History",
            "version": "0.1.0",
            "path": "plugins/brave-history",
            "platforms": ["macos"],
            "package_sha256": PACKAGE_SHA256,
            "display_group": {
                "id": "browser_history",
                "name": "Browser History",
                "name_i18n": {"zh-CN": "浏览器历史"},
                "description": "Manage browser history sources.",
                "description_i18n": {"zh-CN": "统一管理浏览器历史入口。"},
                "icon": "lucide:globe",
                "member_label": "Brave",
                "member_order": 50,
            },
        }
    )

    assert manifest.display_group is not None
    assert manifest.display_group.id == "browser_history"
    assert manifest.display_group.member_label == "Brave"
    assert entry.display_group is not None
    assert entry.display_group.member_order == 50


def test_registry_entry_parses_suggestion_descriptor():
    entry = PluginRegistryEntry.model_validate(
        {
            "plugin_id": "chrome-history",
            "name": "Chrome History",
            "version": "0.1.0",
            "path": "plugins/chrome-history",
            "platforms": ["macos", "windows"],
            "package_sha256": PACKAGE_SHA256,
            "suggestion_descriptor": {
                "category": "browser_history",
                "triggers": {"keywords": {"zh": ["浏览"], "en": ["browsing"]}},
                "platform_support": ["darwin", "win32"],
                "rationale": {"zh": "读取浏览器历史", "en": "read browser history"},
            },
        }
    )
    assert entry.suggestion_descriptor is not None
    assert entry.suggestion_descriptor.category == "browser_history"


def test_registry_entry_without_descriptor_is_none():
    entry = PluginRegistryEntry.model_validate(
        {
            "plugin_id": "x",
            "name": "X",
            "version": "0.1.0",
            "path": "plugins/x",
            "platforms": [],
            "package_sha256": PACKAGE_SHA256,
        }
    )
    assert entry.suggestion_descriptor is None
