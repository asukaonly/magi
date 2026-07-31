from __future__ import annotations

import pytest
from pydantic import ValidationError

from magi_plugin_sdk import PluginManifest, PluginRegistryEntry, PluginRegistryIndex

PACKAGE_SHA256 = "a" * 64


def _entry(
    plugin_id: str,
    *,
    kind: str = "plugin",
    depends_on: list[str] | None = None,
) -> PluginRegistryEntry:
    return PluginRegistryEntry(
        plugin_id=plugin_id,
        name=plugin_id,
        version="1.0.0",
        package_sha256=PACKAGE_SHA256,
        kind=kind,
        depends_on=depends_on or [],
    )


@pytest.mark.parametrize("model", [PluginManifest, PluginRegistryEntry])
@pytest.mark.parametrize(
    "depends_on",
    [
        ["shared-library", "shared-library"],
        ["example"],
    ],
)
def test_package_rejects_duplicate_and_self_dependencies(
    model,
    depends_on: list[str],
) -> None:
    payload = {
        "name": "Example",
        "version": "1.0.0",
        "depends_on": depends_on,
    }
    if model is PluginManifest:
        payload["id"] = "example"
    else:
        payload["plugin_id"] = "example"
        payload["package_sha256"] = PACKAGE_SHA256

    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_registry_rejects_duplicate_plugin_ids() -> None:
    with pytest.raises(ValidationError, match="duplicate plugin id"):
        PluginRegistryIndex(
            registry_version="4",
            plugins=[_entry("example"), _entry("example")],
        )


def test_registry_rejects_missing_dependency() -> None:
    with pytest.raises(ValidationError, match="missing package"):
        PluginRegistryIndex(
            registry_version="4",
            plugins=[_entry("example", depends_on=["shared-library"])],
        )


def test_registry_rejects_non_library_dependency_target() -> None:
    with pytest.raises(ValidationError, match="non-library package"):
        PluginRegistryIndex(
            registry_version="4",
            plugins=[
                _entry("example", depends_on=["shared-package"]),
                _entry("shared-package"),
            ],
        )


def test_registry_rejects_dependency_cycle() -> None:
    with pytest.raises(ValidationError, match="dependency cycle"):
        PluginRegistryIndex(
            registry_version="4",
            plugins=[
                _entry(
                    "library-a",
                    kind="library",
                    depends_on=["library-b"],
                ),
                _entry(
                    "library-b",
                    kind="library",
                    depends_on=["library-a"],
                ),
            ],
        )


def test_registry_accepts_complete_acyclic_library_graph() -> None:
    index = PluginRegistryIndex(
        registry_version="4",
        plugins=[
            _entry("example", depends_on=["library-a"]),
            _entry(
                "library-a",
                kind="library",
                depends_on=["library-b"],
            ),
            _entry("library-b", kind="library"),
        ],
    )

    assert [entry.plugin_id for entry in index.plugins] == [
        "example",
        "library-a",
        "library-b",
    ]


def test_registry_accepts_dependency_chain_larger_than_python_recursion_limit() -> None:
    entries = [_entry("example", depends_on=["library-0"])]
    entries.extend(
        _entry(
            f"library-{index}",
            kind="library",
            depends_on=[f"library-{index + 1}"] if index < 1_199 else [],
        )
        for index in range(1_200)
    )

    index = PluginRegistryIndex(registry_version="4", plugins=entries)

    assert len(index.plugins) == 1_201
