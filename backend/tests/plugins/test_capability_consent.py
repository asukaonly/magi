import pytest

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


@pytest.mark.parametrize("saved", [False, True])
def test_projection_keeps_declared_permissions_distinct_from_saved_consent(saved):
    declared = [
        PluginCapability(capability="network", scope=["new.example"]),
        PluginCapability(capability="calendar"),
    ]
    consented = [PluginCapability(capability="network", scope=["approved.example"])]
    state = _state("p", declared)
    packages = {"p": PluginSettings(consented_capabilities=consented)} if saved else {}
    response = _serialize_package_lightweight(state, packages=packages)
    assert [(c.capability, c.scope) for c in response.manifest.capabilities] == [
        ("network", ["new.example"]),
        ("calendar", []),
    ]
    if saved:
        assert [(c.capability, c.scope) for c in response.manifest.consented_capabilities] == [
            ("network", ["approved.example"])
        ]
    else:
        assert response.manifest.consented_capabilities is None


def test_appconfig_round_trip_preserves_package_origin_and_permission_scope():
    from magi.config import PluginSettings as ExportedPluginSettings
    from magi.config.models import AppConfig

    payload = {
        "plugins": {
            "packages": {
                "demo": {
                    "official": True,
                    "consented_capabilities": [
                        {"capability": "network", "scope": ["approved.example"]}
                    ],
                }
            }
        }
    }
    config = AppConfig.model_validate(payload)
    restored = AppConfig.model_validate_json(config.model_dump_json())
    package = restored.plugins.packages["demo"]
    assert isinstance(package, ExportedPluginSettings)
    assert package.official is True
    assert [(cap.capability, cap.scope) for cap in package.consented_capabilities] == [
        ("network", ["approved.example"])
    ]


def _make_archive(tmp_path: Path, plugin_source: bytes) -> Path:
    toml = (
        b"[plugin]\n"
        b'protocol_version = 2\nmin_sdk_version = "0.2.0"\nexecution_mode = "trusted_process"\n'
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
        source_info = tarfile.TarInfo("demo/plugin.py")
        source_info.size = len(plugin_source)
        tf.addfile(source_info, io.BytesIO(plugin_source))
    return archive


def test_inspect_reads_capabilities_without_installing(tmp_path, monkeypatch):
    from magi.plugins.manager import PluginManager

    mgr = PluginManager.__new__(PluginManager)  # avoid full init
    marker = tmp_path / "plugin-imported"
    user_root = tmp_path / "installed-plugins"
    user_root.mkdir()
    (user_root / "existing-package").write_bytes(b"unchanged")
    monkeypatch.setattr("magi.plugins.package_files.user_plugins_root", lambda: user_root)
    source = f"from pathlib import Path\nPath({str(marker)!r}).write_text('imported')\nraise RuntimeError('plugin must not execute during inspection')\n".encode()
    archive = _make_archive(tmp_path, source)
    inspection = mgr.inspect_plugin_archive(archive)
    manifest = inspection.manifest
    assert manifest.plugin_id == "demo"
    assert manifest.capabilities[0].capability == "network"
    assert manifest.capabilities[0].scope == ["x.com"]
    assert len(inspection.package_sha256) == 64

    assert not marker.exists()
    assert {path.name: path.read_bytes() for path in user_root.iterdir()} == {
        "existing-package": b"unchanged"
    }


@pytest.mark.parametrize(
    "extension,data", [("tar.gz", b"not a gzip tarball"), ("zip", b"PK\x03\x04 not a valid zip")]
)
def test_corrupt_archive_raises_invalid_archive(tmp_path, extension, data):
    # A file with a valid extension but corrupt contents must surface as
    # InvalidPluginArchiveError (a ValueError subclass → routes return a
    # localized HTTP 400), not an unhandled tarfile/gzip error (→ 500).
    import pytest

    from magi.plugins.package_files import InvalidPluginArchiveError
    from magi.plugins.manager import PluginManager

    mgr = PluginManager.__new__(PluginManager)
    bad = tmp_path / f"corrupt.{extension}"
    bad.write_bytes(data)
    with pytest.raises(InvalidPluginArchiveError):
        mgr.inspect_plugin_archive(bad)
    assert issubclass(InvalidPluginArchiveError, ValueError)
