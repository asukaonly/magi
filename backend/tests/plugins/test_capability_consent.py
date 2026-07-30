import io
from pathlib import Path
import tarfile

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
        {
            "plugins": {
                "packages": {"demo": {"consented_capabilities": [{"capability": "calendar"}]}}
            }
        }
    )
    pkg = cfg.plugins.packages["demo"]
    assert pkg.consented_capabilities[0].capability == "calendar"


def _make_archive(tmp_path: Path) -> Path:
    toml = (
        b"[plugin]\n"
        b'id = "demo"\nname = "Demo"\nversion = "1.0.0"\n'
        b'entry_module = "plugin"\nentry_class = "Demo"\n'
        b"\n[[plugin.permissions.capabilities]]\n"
        b'capability = "network"\nscope = ["x.com"]\n'
    )
    archive = tmp_path / "demo.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        info = tarfile.TarInfo("demo/plugin.toml")
        info.size = len(toml)
        tf.addfile(info, io.BytesIO(toml))
    return archive


def test_inspect_reads_capabilities_without_installing(tmp_path):
    from magi.plugins.manager import PluginManager

    mgr = PluginManager.__new__(PluginManager)  # avoid full init
    archive = _make_archive(tmp_path)
    manifest = mgr.inspect_plugin_archive(archive)
    assert manifest.plugin_id == "demo"
    assert manifest.capabilities[0].capability == "network"
    assert manifest.capabilities[0].scope == ["x.com"]


def test_corrupt_targz_raises_invalid_archive(tmp_path):
    # A file with a valid extension but corrupt contents must surface as
    # InvalidPluginArchiveError (a ValueError subclass → routes return a
    # localized HTTP 400), not an unhandled tarfile/gzip error (→ 500).
    import pytest

    from magi.plugins.package_files import InvalidPluginArchiveError
    from magi.plugins.manager import PluginManager

    mgr = PluginManager.__new__(PluginManager)
    bad = tmp_path / "corrupt.tar.gz"
    bad.write_bytes(b"this is definitely not a gzip tarball")
    with pytest.raises(InvalidPluginArchiveError):
        mgr.inspect_plugin_archive(bad)
    assert issubclass(InvalidPluginArchiveError, ValueError)


def test_corrupt_zip_raises_invalid_archive(tmp_path):
    import pytest

    from magi.plugins.package_files import InvalidPluginArchiveError
    from magi.plugins.manager import PluginManager

    mgr = PluginManager.__new__(PluginManager)
    bad = tmp_path / "corrupt.zip"
    bad.write_bytes(b"PK\x03\x04 not really a valid zip archive")
    with pytest.raises(InvalidPluginArchiveError):
        mgr.inspect_plugin_archive(bad)


def test_candidate_routes_exposed_on_public_router():
    # The route must also be in the _PUBLIC_ROUTE_METHODS allowlist, NOT just on
    # the router — register_api_routes filters the public app through that
    # allowlist, so a route missing from it is silently dropped (HTTP 404 in the
    # running app even though unit tests that import the router directly pass).
    from magi.api.routers.plugins import plugins_router
    from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router

    public = _build_public_router(plugins_router, _PUBLIC_ROUTE_METHODS["plugins"])
    paths = {r.path for r in public.routes}
    assert "/install/candidates" in paths
    assert "/install/candidates/{candidate_id}" in paths
    assert "/install/candidates/{candidate_id}/jobs" in paths
