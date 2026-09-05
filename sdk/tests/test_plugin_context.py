"""Explicit per-instance SDK context binding."""

import pytest
from magi_plugin_sdk.base import Plugin
from magi_plugin_sdk.context import PluginContext
from magi_plugin_sdk.contracts import PluginManifest
from magi_plugin_sdk.runtime import PluginConnection


class Credentials:
    def get(self, key):
        return None
    def set(self, key, value):
        pass
    def delete(self, key):
        pass


def test_configure_requires_connection_and_host_context(tmp_path):
    manifest = PluginManifest(plugin_id="example", name="Example", version="0.2.0")
    connection = PluginConnection(connection_id="conn_one", plugin_id="example", display_name="Work", settings={"nested": {"value": 1}})
    context = PluginContext(connection, tmp_path / "state", tmp_path / "resources", Credentials())
    plugin = Plugin()
    plugin.configure(manifest=manifest, connection=connection, context=context)
    assert plugin.connection_id == "conn_one"
    assert plugin.context.state_dir == tmp_path / "state"
    plugin.settings["nested"]["value"] = 2
    assert connection.settings["nested"]["value"] == 1
    with pytest.raises(TypeError):
        plugin.configure(manifest=manifest, settings={})


def test_cross_connection_context_and_relative_paths_are_rejected(tmp_path):
    manifest = PluginManifest(plugin_id="example", name="Example", version="0.2.0")
    connection = PluginConnection(connection_id="one", plugin_id="example", display_name="Work")
    other = connection.model_copy(update={"connection_id": "two"})
    context = PluginContext(other, tmp_path / "state", tmp_path / "resources", Credentials())
    with pytest.raises(ValueError, match="bindings"):
        Plugin().configure(manifest=manifest, connection=connection, context=context)
    with pytest.raises(ValueError, match="absolute"):
        PluginContext(connection, type(tmp_path)("relative"), tmp_path / "resources", Credentials())
