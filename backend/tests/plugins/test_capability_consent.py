from magi.config.plugin_models import PluginSettings
from magi.plugins.contracts import (
    PluginCapability,
    PluginManifest,
    PluginPackageState,
    PluginPermissions,
)
from magi.api.routers.plugins_common import _serialize_package_lightweight


def test_plugin_settings_consented_default_none():
    assert PluginSettings().consented_capabilities is None
    s = PluginSettings(consented_capabilities=[PluginCapability(capability="network")])
    assert s.consented_capabilities[0].capability == "network"


def _state(plugin_id, caps):
    return PluginPackageState(
        manifest=PluginManifest(
            id=plugin_id,
            name=plugin_id,
            version="1.0.0",
            source="external",
            permissions=PluginPermissions(capabilities=caps),
        ),
        enabled=True,
    )


def test_projection_includes_declared_and_consented():
    declared = [PluginCapability(capability="network", scope=["a.com"])]
    consented = [PluginCapability(capability="network", scope=["a.com"])]
    state = _state("p", declared)
    packages = {"p": PluginSettings(consented_capabilities=consented)}
    resp = _serialize_package_lightweight(state, packages=packages)
    assert [c.capability for c in resp.manifest.capabilities] == ["network"]
    assert resp.manifest.consented_capabilities[0].scope == ["a.com"]


def test_projection_consented_none_when_absent():
    state = _state("p", [PluginCapability(capability="calendar")])
    resp = _serialize_package_lightweight(state, packages={})
    assert resp.manifest.consented_capabilities is None
    assert resp.manifest.capabilities[0].capability == "calendar"
