import pytest

from magi.config.plugin_models import PluginSettings
from magi.api.routers.plugins_common import (
    _authoritative_official,
    install_with_closure,
)
from magi.plugins.contracts import (
    PluginManifest,
    PluginPackageState,
    PluginRegistryEntry,
)


class _FakeManifest:
    def __init__(self, plugin_id, source, official):
        self.plugin_id = plugin_id
        self.source = source
        self.official = official


def _cfg_with(plugin_id, official):
    # Minimal stand-in for config.plugins.packages[plugin_id]
    return {plugin_id: PluginSettings(official=official)}


def test_builtin_trusts_its_manifest_official(monkeypatch):
    m = _FakeManifest("core-tools", "builtin", True)
    # builtin path ignores config; reads manifest
    assert _authoritative_official(m, packages={}) is True


def test_non_builtin_reads_persisted_official_true(monkeypatch):
    m = _FakeManifest("calendar", "external", False)  # manifest says false
    pkgs = _cfg_with("calendar", True)                 # registry persisted true
    assert _authoritative_official(m, packages=pkgs) is True


def test_non_builtin_ignores_forged_manifest_official(monkeypatch):
    m = _FakeManifest("evil", "external", True)        # forged self-declare
    pkgs = _cfg_with("evil", False)                    # registry says false
    assert _authoritative_official(m, packages=pkgs) is False


def test_non_builtin_missing_config_defaults_false(monkeypatch):
    m = _FakeManifest("legacy", "external", True)       # forged
    assert _authoritative_official(m, packages={}) is False  # no persisted entry


def test_plugin_settings_has_official_field():
    s = PluginSettings(official=True)
    assert s.official is True
    assert PluginSettings().official is None  # default: unknown


# --- Persist-path coverage (regression for the manager-branch install) -------
#
# The helper tests above only exercise _authoritative_official + the field
# default; none of them assert that the *install* path actually persists the
# registry's official value. That gap let a bug ship where the persist lived
# only on the manager-is-None lightweight path, so in a running app (manager
# initialized) the install went through install_plugin_from_directory + scan,
# which conservatively persists official=False for external plugins, and the
# registry's official value was never written. These tests drive the real
# install_with_closure manager branch and assert the authoritative value is
# persisted after install.


class _FakeManager:
    """Stand-in for PluginManager exposing only what install_with_closure uses."""

    def __init__(self):
        self._package_states = {}
        self.installed_dirs = []

    def installed_plugin_ids(self):
        return set(self._package_states)

    def install_plugin_from_directory(self, plugin_dir, *, progress_reporter=None):
        # Mirror the real manager: scan -> _persist_new_packages would have
        # written official=False for an external plugin. We don't run a real
        # scan here; the explicit save_config after this call (the code under
        # test) is what must write the authoritative official value.
        self.installed_dirs.append(plugin_dir)
        manifest = PluginManifest(
            id="calendar",
            name="Calendar",
            version="1.0.0",
            source="external",
            official=False,  # local manifest is untrusted; never the authority
        )
        return PluginPackageState(manifest=manifest, enabled=True)


class _FakeRegistry:
    """Stand-in for PluginRegistryClient with a single official entry."""

    def __init__(self, *, official):
        self.entry = PluginRegistryEntry(
            plugin_id="calendar",
            name="Calendar",
            version="1.0.0",
            official=official,
        )

    async def fetch_entry(self, plugin_id):
        return self.entry if plugin_id == self.entry.plugin_id else None

    async def clone_plugin(self, entry):
        return "/tmp/fake-calendar"


@pytest.mark.asyncio
@pytest.mark.parametrize("official", [True, False])
async def test_install_with_closure_persists_registry_official(monkeypatch, official):
    """The manager-branch install must persist the registry's official value.

    Drives install_with_closure with a fake manager + fake registry and
    asserts save_config was called with
    ``plugins.packages.<id>.official == entry.official``. This fails against
    the pre-fix code (where the manager branch never persisted official).
    """
    recorded: list[dict] = []

    def _record_save_config(updates):
        recorded.append(updates)
        return True

    # install_with_closure does `from ...config import save_config`, which
    # binds from the magi.config package namespace at call time, so patch
    # the attribute there.
    monkeypatch.setattr("magi.config.save_config", _record_save_config)

    manager = _FakeManager()
    registry = _FakeRegistry(official=official)

    target_state, extra = await install_with_closure(
        "calendar", registry, manager
    )

    assert extra == []
    assert manager.installed_dirs == ["/tmp/fake-calendar"]

    official_key = "plugins.packages.calendar.official"
    official_writes = [
        u[official_key] for u in recorded if official_key in u
    ]
    assert official_writes, (
        "manager-branch install must persist the registry official value; "
        f"recorded save_config calls: {recorded}"
    )
    assert official_writes[-1] is official
