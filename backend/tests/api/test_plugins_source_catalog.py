"""Exercise source browsing through the product router, including trust boundaries."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from magi.api.routers import plugins_source_catalog as catalog
from magi.api.routers.plugins import plugins_router
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.availability.contracts import AvailabilityReason


def source(plugin_id, **changes):
    descriptor = SimpleNamespace(
        category="browser_history", icon="lucide:globe",
        surfaces=SimpleNamespace(first_context=SimpleNamespace(
            scope=SimpleNamespace(model_dump=lambda: {"en": "Last 7 days", "zh": "最近 7 天"}),
        )),
    )
    values = dict(plugin_id=plugin_id, name=plugin_id, name_i18n={}, description="",
                  description_i18n={}, contribution_types=["source"],
                  suggestion_descriptor=descriptor, activation_flow=object(), icon="lucide:globe")
    return SimpleNamespace(**(values | changes))


@pytest.fixture
def context(monkeypatch):
    entries, packages, active = [], [], set()
    snapshot = SimpleNamespace(index=SimpleNamespace(plugins=entries), official_source=True)
    fetch = AsyncMock(return_value=snapshot)
    resolver = Mock()
    resolver.evaluate_descriptor.return_value = SimpleNamespace(available=True, reason=AvailabilityReason.AVAILABLE)
    monkeypatch.setattr(catalog, "_get_registry_client", lambda: SimpleNamespace(fetch_snapshot=fetch))
    monkeypatch.setattr(catalog, "_try_plugin_manager", lambda: SimpleNamespace(list_packages=lambda: packages))
    monkeypatch.setattr(catalog, "_active_source_plugin_ids", AsyncMock(return_value=active))
    monkeypatch.setattr(catalog, "_get_or_create_resolver", lambda: resolver)
    app = FastAPI()
    app.include_router(_build_public_router(plugins_router, _PUBLIC_ROUTE_METHODS["plugins"]), prefix="/api/plugins")
    with TestClient(app) as client:
        yield SimpleNamespace(entries=entries, packages=packages, active=active,
                              snapshot=snapshot, fetch=fetch, resolver=resolver, client=client)


def read(context):
    response = context.client.get("/api/plugins/source-catalog")
    assert response.status_code == 200, response.text
    return response.json()


def test_full_catalog_keeps_siblings_active_sources_and_more_than_five(context):
    context.entries.extend(source(f"browser-{index}") for index in range(7))
    context.entries.append(source("tool-only", contribution_types=["tool"]))
    context.active.add("browser-0")
    result = read(context)
    assert result["catalog_mode"] == "full"
    assert len(result["items"]) == 7
    assert result["items"][0]["status"] == "connected"
    assert result["items"][1]["scope"]["en"] == "Last 7 days"
    assert context.resolver.evaluate_descriptor.call_count == 6


@pytest.mark.parametrize("reason", [AvailabilityReason.UNSUPPORTED_PLATFORM,
    AvailabilityReason.MISSING_FILE, AvailabilityReason.MISSING_EXECUTABLE,
    AvailabilityReason.APP_NOT_INSTALLED, AvailabilityReason.CHECK_ERROR])
def test_unavailable_entries_keep_the_actual_reason(context, reason):
    context.entries.append(source("unavailable"))
    context.resolver.evaluate_descriptor.return_value = SimpleNamespace(available=False, reason=reason)
    assert read(context)["items"][0]["status"] == reason.value


def test_custom_registry_does_not_authorize_local_probes(context):
    context.snapshot.official_source = False
    context.entries.extend([source("custom", official=True), source("installed")])
    context.packages.append(SimpleNamespace(manifest=source("installed", name="Local manifest")))
    items = {item["plugin_id"]: item for item in read(context)["items"]}
    assert items["custom"]["status"] == "review_in_settings"
    assert items["installed"]["installed"] is True
    assert items["installed"]["name"] == "Local manifest"
    assert context.resolver.evaluate_descriptor.call_count == 1
    assert context.resolver.evaluate_descriptor.call_args.kwargs["plugin_id"] == "installed"


def test_offline_catalog_preserves_installed_sources(context):
    context.fetch.side_effect = RuntimeError("Registry unavailable")
    context.packages.append(SimpleNamespace(manifest=source("local")))
    response = read(context)
    assert response["catalog_mode"] == "installed_only"
    assert response["items"][0]["plugin_id"] == "local"


def test_sources_without_first_context_setup_remain_discoverable(context):
    context.entries.extend([source("no-descriptor", suggestion_descriptor=None),
                            source("no-flow", activation_flow=None)])
    items = {item["plugin_id"]: item for item in read(context)["items"]}
    assert items["no-descriptor"]["status"] == "no_descriptor"
    assert items["no-flow"]["status"] == "setup_in_settings"
