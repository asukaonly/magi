"""Fixtures for availability subsystem tests."""

from __future__ import annotations

import pytest

from magi_plugin_sdk.contracts import (
    LocalizedText,
    LocalRequirementAppInstalled,
    LocalRequirementExecutableInPath,
    LocalRequirementFileExists,
    PluginManifest,
    SuggestionDescriptor,
    Triggers,
)


def _make_manifest(
    plugin_id: str,
    *,
    requirements: list = None,
    platforms: list[str] = None,
) -> PluginManifest:
    return PluginManifest(
        id=plugin_id,
        name=plugin_id.replace("-", " ").title(),
        version="0.1.0",
        entry_module="plugin",
        entry_class="X",
        suggestion_descriptor=SuggestionDescriptor(
            category="test_category",
            triggers=Triggers(intents=["x"]),
            platform_support=platforms or ["darwin", "win32", "linux"],
            local_requirements=requirements or [],
            rationale=LocalizedText(zh="测试", en="test"),
        ),
    )


@pytest.fixture
def make_manifest():
    return _make_manifest


@pytest.fixture
def manifest_without_descriptor() -> PluginManifest:
    return PluginManifest(
        id="legacy",
        name="Legacy",
        version="0.1.0",
        entry_module="plugin",
        entry_class="X",
    )
