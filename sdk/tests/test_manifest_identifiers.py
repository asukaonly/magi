from __future__ import annotations

import pytest
from pydantic import ValidationError

from magi_plugin_sdk import PluginManifest, PluginRegistryEntry


@pytest.mark.parametrize(
    "plugin_id",
    [
        "",
        "../escape",
        "/tmp/escape",
        "Uppercase",
        "contains.dot",
        "contains space",
        "a" * 65,
    ],
)
def test_manifest_rejects_invalid_plugin_identifier(plugin_id: str) -> None:
    with pytest.raises(ValidationError):
        PluginManifest(id=plugin_id, name="Example", version="1.0.0")


def test_manifest_accepts_bounded_plugin_identifiers() -> None:
    manifest = PluginManifest(
        id="plugin_name-1",
        name="Example",
        version="1.0.0",
        depends_on=["shared_library-1", "a" * 64],
    )

    assert manifest.plugin_id == "plugin_name-1"
    assert manifest.depends_on == ["shared_library-1", "a" * 64]


@pytest.mark.parametrize(
    "plugin_id",
    ["index", "con", "prn", "aux", "nul", "com1", "com9", "lpt1", "lpt9"],
)
def test_manifest_rejects_reserved_plugin_identifiers(plugin_id: str) -> None:
    with pytest.raises(ValidationError, match="reserved"):
        PluginManifest(id=plugin_id, name="Example", version="1.0.0")


@pytest.mark.parametrize("dependency_id", ["../escape", "BadDependency", "a" * 65])
def test_manifest_rejects_invalid_dependency_identifier(dependency_id: str) -> None:
    with pytest.raises(ValidationError):
        PluginManifest(
            id="example",
            name="Example",
            version="1.0.0",
            depends_on=[dependency_id],
        )


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("entry_module", "../plugin"),
        ("entry_module", "package.plugin"),
        ("entry_module", "class"),
        ("entry_class", "../../Plugin"),
        ("entry_class", "Plugin.Class"),
        ("entry_class", "None"),
    ],
)
def test_manifest_rejects_non_identifier_entrypoints(field_name: str, value: str) -> None:
    payload = {
        "id": "example",
        "name": "Example",
        "version": "1.0.0",
        field_name: value,
    }

    with pytest.raises(ValidationError):
        PluginManifest.model_validate(payload)


def test_registry_entry_uses_the_same_identifier_contract() -> None:
    with pytest.raises(ValidationError):
        PluginRegistryEntry(
            plugin_id="../../escape",
            name="Example",
            version="1.0.0",
            package_sha256="a" * 64,
        )

    with pytest.raises(ValidationError):
        PluginRegistryEntry(
            plugin_id="example",
            name="Example",
            version="1.0.0",
            package_sha256="a" * 64,
            depends_on=["BadDependency"],
        )


@pytest.mark.parametrize("model", [PluginManifest, PluginRegistryEntry])
@pytest.mark.parametrize(
    "version",
    [
        "1",
        "1.0",
        "01.0.0",
        "1.0.0-beta",
        "1.0.0+build",
        "latest",
        f"{'1' * 33}.0.0",
    ],
)
def test_plugin_versions_require_canonical_major_minor_patch(model, version: str) -> None:
    payload = {
        "name": "Example",
        "version": version,
    }
    if model is PluginManifest:
        payload["id"] = "example"
    else:
        payload["plugin_id"] = "example"
        payload["package_sha256"] = "a" * 64

    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize("model", [PluginManifest, PluginRegistryEntry])
def test_package_rejects_more_than_eight_direct_dependencies(model) -> None:
    payload = {
        "name": "Example",
        "version": "1.0.0",
        "depends_on": [f"library-{index}" for index in range(9)],
    }
    identifier_field = "id" if model is PluginManifest else "plugin_id"
    if model is PluginRegistryEntry:
        payload["package_sha256"] = "a" * 64
    payload[identifier_field] = "example"

    with pytest.raises(ValidationError):
        model.model_validate(payload)
