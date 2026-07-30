from __future__ import annotations

import json
from pathlib import Path

import pytest

from magi.plugins.contracts import (
    ContributionType,
    PluginCapability,
    PluginManifest,
    PluginPermissions,
    PluginRegistryEntry,
    PluginRegistryIndex,
)
from magi.plugins.discovery import load_plugin_manifest
from magi.plugins.install_service import validate_registry_package


def _manifest() -> PluginManifest:
    return PluginManifest(
        id="demo-plugin",
        name="Demo Plugin",
        version="1.0.0",
        description="Demo",
        author="Example",
        contribution_types=[ContributionType.TOOL],
        depends_on=["demo-library"],
        platforms=["darwin"],
        permissions=PluginPermissions(
            capabilities=[
                PluginCapability(
                    capability="network",
                    scope=["example.com"],
                    reason="Fetch data",
                )
            ]
        ),
    )


def _entry() -> PluginRegistryEntry:
    manifest = _manifest()
    return PluginRegistryEntry(
        plugin_id=manifest.plugin_id,
        name=manifest.name,
        version=manifest.version,
        description=manifest.description,
        author=manifest.author,
        contribution_types=[item.value for item in manifest.contribution_types],
        depends_on=list(manifest.depends_on),
        platforms=list(manifest.platforms),
        capabilities=list(manifest.capabilities),
    )


@pytest.mark.parametrize(
    ("field_name", "changed_manifest"),
    [
        ("plugin_id", _manifest().model_copy(update={"plugin_id": "other-plugin"})),
        ("version", _manifest().model_copy(update={"version": "2.0.0"})),
        ("kind", _manifest().model_copy(update={"kind": "library"})),
        ("depends_on", _manifest().model_copy(update={"depends_on": []})),
        (
            "capabilities",
            _manifest().model_copy(
                update={
                    "permissions": PluginPermissions(
                        capabilities=[
                            PluginCapability(
                                capability="network",
                                scope=["other.example"],
                                reason="Different consent",
                            )
                        ]
                    )
                }
            ),
        ),
    ],
)
def test_registry_package_rejects_shared_manifest_mismatches(
    field_name: str,
    changed_manifest: PluginManifest,
) -> None:
    with pytest.raises(ValueError, match=field_name):
        validate_registry_package(_entry(), changed_manifest)


def test_registry_package_uses_canonical_data_locality_and_optional_fields() -> None:
    manifest = PluginManifest.model_validate(
        {
            **_manifest().model_dump(mode="json", by_alias=True),
            "min_sdk_version": "0.1.0",
            "suggestion_descriptor": {
                "category": "demo",
                "triggers": {"any": []},
                "platform_support": ["darwin"],
                "rationale": {"zh": "演示", "en": "Demo"},
                "data_locality": "local_only",
            },
        }
    )
    entry = _entry().model_copy(
        update={
            "data_locality": "local_only",
            "suggestion_descriptor": manifest.suggestion_descriptor,
        }
    )

    validate_registry_package(entry, manifest)


def test_local_plugin_registry_matches_current_manifests_when_available() -> None:
    repository_root = Path(__file__).resolve().parents[4] / "magi-plugins"
    registry_path = repository_root / "registry.json"
    if not registry_path.is_file():
        pytest.skip("Sibling magi-plugins checkout is unavailable")

    index = PluginRegistryIndex.model_validate_json(registry_path.read_bytes())
    for entry in index.plugins:
        manifest_path = repository_root / entry.path / "plugin.toml"
        manifest = load_plugin_manifest(manifest_path, source="external")
        validate_registry_package(entry, manifest)

    assert len(json.loads(registry_path.read_text(encoding="utf-8"))["plugins"]) == len(
        index.plugins
    )
