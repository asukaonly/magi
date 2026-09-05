"""Explicit connection fixtures for manager tests, independent of worker transport."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

from magi_plugin_sdk import Plugin, PluginManifest
from magi_plugin_sdk.context import PluginContext
from magi_plugin_sdk.runtime import PluginConnection


def instantiate_fixture_plugin(manifest, connection, context):
    """Use the host-injected factory seam to load only generated test packages."""
    path = Path(manifest.plugin_dir) / f"{manifest.entry_module}.py"
    name = f"magi_plugin_{manifest.plugin_id.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(name, path, submodule_search_locations=[str(path.parent)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    plugin = getattr(module, manifest.entry_class)()
    plugin.configure(manifest=manifest, connection=connection, context=context)
    return plugin


def bind_fixture_plugin(plugin: Plugin, plugin_id: str, *, root: Path, settings=None,
                        source_types=()) -> Plugin:
    """Bind a test instance to an explicit account and scoped host paths."""
    manifest = PluginManifest(id=plugin_id, name=plugin_id, version="1.0.0", source="external",
                              projection_sources=list(source_types))
    connection = PluginConnection(connection_id=f"test:{plugin_id}", plugin_id=plugin_id,
                                  display_name=plugin_id, enabled=True, settings=settings or {})
    context = PluginContext(connection=connection, state_dir=root / plugin_id / "state",
                            resources_dir=root / plugin_id / "resources", credentials=None)
    plugin.configure(manifest=manifest, connection=connection, context=context)
    return plugin
