"""SDK catalog preservation through the product's public plugin router."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from magi.api.routers import plugins_registry_routes
from magi.api.routers.plugins import plugins_router
from magi.api.routers.plugins_schemas import PluginRegistryEntryResponse
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.plugins.contracts import PluginRegistryIndex


CATALOG_FIELDS = (
    "protocol_version",
    "execution_mode",
    "min_sdk_version",
    "settings_fields",
    "activation_flow",
    "settings_actions",
    "settings_resources",
    "settings_ui_blocks",
)


def _public_catalog(monkeypatch, index: PluginRegistryIndex, *, include_libraries: bool = True):
    async def fetch_snapshot(*, force: bool = False):
        return SimpleNamespace(index=index, install_fingerprint="a" * 64, official_source=True)

    monkeypatch.setattr(
        plugins_registry_routes,
        "_get_registry_client",
        lambda: SimpleNamespace(fetch_snapshot=fetch_snapshot),
    )
    monkeypatch.setattr(plugins_registry_routes, "_try_plugin_manager", lambda: None)
    app = FastAPI()
    app.include_router(
        _build_public_router(plugins_router, _PUBLIC_ROUTE_METHODS["plugins"]),
        prefix="/api/plugins",
    )
    response = TestClient(app).get(
        "/api/plugins/registry", params={"include": "libraries"} if include_libraries else {}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _assert_catalog_preserved(payload, entries):
    assert payload["registry_version"] == "4"
    assert payload["install_fingerprint"] == "a" * 64
    assert len(payload["plugins"]) == len(entries)
    actual = {entry["plugin_id"]: entry for entry in payload["plugins"]}
    for entry in entries:
        expected = entry.model_dump(mode="json")
        for field in CATALOG_FIELDS:
            assert actual[entry.plugin_id][field] == expected[field], (entry.plugin_id, field)


@pytest.fixture
def catalog_index():
    return PluginRegistryIndex.model_validate(
        {
            "registry_version": "4",
            "plugins": [
                {
                    "plugin_id": f"catalog-{number}",
                    "name": f"Catalog {number}",
                    "version": "0.2.0",
                    "package_sha256": "b" * 64,
                    "kind": "library" if number < 3 else "plugin",
                    "protocol_version": 2,
                    "min_sdk_version": "0.2.0",
                    "execution_mode": "restricted_process" if number % 2 else "trusted_process",
                    "settings_fields": [
                        {
                            "key": "batch_size",
                            "type": "number",
                            "label": "Batch size",
                            "default": 20,
                            "minimum": 1,
                            "maximum": 100,
                        }
                    ],
                    "activation_flow": {
                        "title": "Connect account",
                        "enabled_key": "enabled",
                        "configured_key": "configured",
                        "fields": [
                            {"key": "token", "type": "secret", "label": "Token", "required": True}
                        ],
                    },
                    "settings_actions": [
                        {
                            "action_id": "check_account",
                            "label": "Check account",
                            "depends_on_key": "mode",
                            "depends_on_values": ["remote"],
                            "requires_enabled": False,
                        }
                    ],
                    "settings_resources": [
                        {
                            "resource_name": "accounts",
                            "resource_type": "collection",
                            "metadata": {"columns": [{"key": "name", "label": "Name"}]},
                        }
                    ],
                    "settings_ui_blocks": [
                        {
                            "block_id": "accounts",
                            "title": "Accounts",
                            "resource_name": "accounts",
                            "value_key": "account_ids",
                            "presentation": "list",
                        }
                    ],
                }
                for number in range(25)
            ],
        }
    )


@pytest.mark.parametrize("include_libraries", [True, False])
def test_public_registry_preserves_all_sdk_catalog_fields(
    monkeypatch, catalog_index, include_libraries
):
    payload = _public_catalog(monkeypatch, catalog_index, include_libraries=include_libraries)
    entries = [
        entry for entry in catalog_index.plugins if include_libraries or entry.kind != "library"
    ]
    _assert_catalog_preserved(payload, entries)
    assert len(entries) == (25 if include_libraries else 22)


@pytest.mark.parametrize("field", ["protocol_version", "execution_mode", "min_sdk_version"])
def test_registry_response_requires_explicit_runtime_metadata(catalog_index, field):
    values = catalog_index.plugins[0].model_dump(mode="json")
    values.pop(field)
    with pytest.raises(ValidationError) as error:
        PluginRegistryEntryResponse.model_validate(values)
    assert any(
        item["loc"] == (field,) and item["type"] == "missing" for item in error.value.errors()
    )


def test_paired_repository_catalog_reaches_public_route_unchanged(monkeypatch):
    repository = Path(
        os.environ.get(
            "MAGI_PLUGINS_REPO", Path(__file__).resolve().parents[4] / "magi-plugins-runtime"
        )
    )
    registry_file = repository / "registry.json"
    if not registry_file.is_file():
        pytest.skip("Paired plugin repository is unavailable")
    index = PluginRegistryIndex.model_validate_json(registry_file.read_bytes())
    payload = _public_catalog(monkeypatch, index)
    _assert_catalog_preserved(payload, index.plugins)
    assert len(index.plugins) >= 25
