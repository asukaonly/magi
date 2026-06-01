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


def test_config_exported_plugin_settings_has_capability_fields():
    # Guards against the duplicate-model bug: the PluginSettings that AppConfig
    # actually uses (re-exported from magi.config) must carry these fields, or
    # consented_capabilities/official get silently dropped on config load.
    from magi.config import PluginSettings as ExportedPluginSettings

    s = ExportedPluginSettings.model_validate(
        {"official": True, "consented_capabilities": [{"capability": "network"}]}
    )
    assert s.official is True
    assert s.consented_capabilities[0].capability == "network"


def test_appconfig_round_trips_consented_capabilities():
    # End-to-end: a package's consented_capabilities survives AppConfig validation
    # (the real model path), not just direct plugin_models construction.
    from magi.config.models import AppConfig

    cfg = AppConfig.model_validate(
        {"plugins": {"packages": {"demo": {"consented_capabilities": [{"capability": "calendar"}]}}}}
    )
    pkg = cfg.plugins.packages["demo"]
    assert pkg.consented_capabilities[0].capability == "calendar"
