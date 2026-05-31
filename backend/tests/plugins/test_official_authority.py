from magi.config.plugin_models import PluginSettings
from magi.api.routers.plugins_common import _authoritative_official


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
