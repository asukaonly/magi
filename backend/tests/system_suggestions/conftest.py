"""Fixtures for system_suggestions tests."""

from __future__ import annotations

import pytest

from magi_plugin_sdk.contracts import (
    LocalizedText,
    PluginManifest,
    SuggestionDescriptor,
    Triggers,
)


def make_manifest(
    plugin_id: str,
    *,
    category: str,
    keywords: dict[str, list[str]] | None = None,
    intents: list[str] | None = None,
    platforms: list[str] | None = None,
) -> PluginManifest:
    return PluginManifest(
        id=plugin_id,
        name=plugin_id,
        version="0.1.0",
        entry_module="plugin",
        entry_class="X",
        suggestion_descriptor=SuggestionDescriptor(
            category=category,
            triggers=Triggers(
                intents=intents or [],
                entities=[],
                keywords=keywords or {},
            ),
            platform_support=platforms or ["darwin", "win32", "linux"],
            local_requirements=[],
            rationale=LocalizedText(
                zh=f"connect {plugin_id} (zh)",
                en=f"connect {plugin_id} (en)",
            ),
        ),
    )


@pytest.fixture
def make_manifest_fixture():
    return make_manifest
