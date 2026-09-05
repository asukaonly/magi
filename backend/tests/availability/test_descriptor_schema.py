# backend/tests/availability/test_descriptor_schema.py
"""Schema validation for SuggestionDescriptor and its sub-models.

These tests pin the contract that plugin authors will write descriptors against.
Breakage here is a public-API change and requires SDK version bump."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from magi_plugin_sdk.contracts import (
    LocalizedText,
    LocalRequirementAppInstalled,
    LocalRequirementExecutableInPath,
    LocalRequirementFileExists,
    PluginManifest,
    SuggestionDescriptor,
    Triggers,
)


def test_suggestion_descriptor_minimal_valid() -> None:
    descriptor = SuggestionDescriptor(
        category="browser_history",
        triggers=Triggers(intents=["user_asks_about_browsing"]),
        platform_support=["darwin", "win32", "linux"],
        rationale=LocalizedText(
            zh="magi 会读取你的 Chrome 历史回答这类问题",
            en="magi will read your Chrome history to answer these questions",
        ),
    )
    assert descriptor.category == "browser_history"
    assert descriptor.setup_time_estimate_seconds == 30  # default
    assert descriptor.data_locality == "local_only"  # default
    assert descriptor.local_requirements == []  # default empty


def test_suggestion_descriptor_with_file_exists_requirement() -> None:
    descriptor = SuggestionDescriptor(
        category="browser_history",
        triggers=Triggers(intents=["user_asks_about_browsing"]),
        platform_support=["darwin", "win32"],
        local_requirements=[
            LocalRequirementFileExists(
                check_kind="file_exists",
                paths_per_platform={
                    "darwin": "~/Library/Application Support/Google/Chrome/Default/History",
                    "win32": "%LOCALAPPDATA%/Google/Chrome/User Data/Default/History",
                },
            )
        ],
        rationale=LocalizedText(zh="测试", en="test"),
    )
    assert len(descriptor.local_requirements) == 1
    assert descriptor.local_requirements[0].check_kind == "file_exists"


def test_suggestion_descriptor_discriminated_requirement_union() -> None:
    """All check_kind variants must round-trip through dict serialization."""
    descriptor = SuggestionDescriptor(
        category="code_activity",
        triggers=Triggers(entities=["repository", "commit"]),
        platform_support=["darwin", "win32", "linux"],
        local_requirements=[
            LocalRequirementExecutableInPath(check_kind="executable_in_path", names=["git"]),
            LocalRequirementAppInstalled(
                check_kind="app_installed",
                identifier_per_platform={"darwin": "com.apple.dt.Xcode"},
            ),
        ],
        rationale=LocalizedText(zh="测试", en="test"),
    )
    dumped = descriptor.model_dump()
    reloaded = SuggestionDescriptor.model_validate(dumped)
    assert reloaded.local_requirements[0].check_kind == "executable_in_path"
    assert reloaded.local_requirements[1].check_kind == "app_installed"


def test_suggestion_descriptor_rejects_unknown_check_kind() -> None:
    with pytest.raises(ValidationError):
        SuggestionDescriptor(
            category="x",
            triggers=Triggers(),
            platform_support=["darwin"],
            local_requirements=[{"check_kind": "supernatural_divination"}],
            rationale=LocalizedText(zh="测试", en="test"),
        )


def test_plugin_manifest_descriptor_optional() -> None:
    """Existing plugins without suggestion_descriptor must still parse."""
    manifest = PluginManifest(
        id="legacy-plugin",
        name="Legacy",
        version="1.0.0",
        entry_module="plugin",
        entry_class="LegacyPlugin",
    )
    assert manifest.suggestion_descriptor is None


def test_plugin_manifest_with_descriptor() -> None:
    manifest = PluginManifest(
        id="chrome-history",
        name="Chrome History",
        version="0.1.0",
        entry_module="plugin",
        entry_class="ChromeHistoryPlugin",
        suggestion_descriptor=SuggestionDescriptor(
            category="browser_history",
            triggers=Triggers(intents=["user_asks_about_browsing"]),
            platform_support=["darwin"],
            rationale=LocalizedText(zh="测试", en="test"),
        ),
    )
    assert manifest.suggestion_descriptor is not None
    assert manifest.suggestion_descriptor.category == "browser_history"


def test_plugin_manifest_parses_descriptor_from_toml() -> None:
    """A plugin.toml that includes [plugin.suggestion_descriptor] must load.

    This mirrors the wire format authors will write.
    """
    import tomllib

    toml_text = """
[plugin]
id = "chrome-history"
name = "Chrome History"
version = "0.1.0"
entry_module = "plugin"
entry_class = "ChromeHistoryPlugin"
contribution_types = ["source"]

[plugin.suggestion_descriptor]
category = "browser_history"
setup_time_estimate_seconds = 10
data_locality = "local_only"
platform_support = ["darwin", "win32", "linux"]

[plugin.suggestion_descriptor.triggers]
intents = ["user_asks_about_browsing"]
entities = ["url", "website"]

[plugin.suggestion_descriptor.triggers.keywords]
zh = ["浏览", "上网", "看过"]
en = ["browsing", "website", "read online"]

[plugin.suggestion_descriptor.rationale]
zh = "magi 会读取你的 Chrome 历史回答这类问题"
en = "magi will read your Chrome history to answer these questions"

[[plugin.suggestion_descriptor.local_requirements]]
check_kind = "file_exists"

[plugin.suggestion_descriptor.local_requirements.paths_per_platform]
darwin = "~/Library/Application Support/Google/Chrome/Default/History"
win32 = "%LOCALAPPDATA%/Google/Chrome/User Data/Default/History"
linux = "~/.config/google-chrome/Default/History"
"""
    raw = tomllib.loads(toml_text)
    manifest = PluginManifest.model_validate(raw["plugin"])
    assert manifest.suggestion_descriptor is not None
    assert manifest.suggestion_descriptor.category == "browser_history"
    assert manifest.suggestion_descriptor.triggers.keywords["zh"] == [
        "浏览",
        "上网",
        "看过",
    ]
    assert len(manifest.suggestion_descriptor.local_requirements) == 1
    req = manifest.suggestion_descriptor.local_requirements[0]
    assert req.check_kind == "file_exists"
    assert "darwin" in req.paths_per_platform
