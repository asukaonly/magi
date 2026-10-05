from __future__ import annotations

from magi_plugin_sdk import (
    ContributionType,
    HistoryImportParseResult,
    HistoryImporterSpec,
    Plugin,
    PluginManifest,
)

from magi.plugins.contribution_registration import PluginContributionRegistrar
from magi.plugins.history_importers import HistoryImporterRegistry
from magi.plugins.sources import SourceRegistry
from magi_plugin_sdk.context import PluginContext
from magi_plugin_sdk.runtime import PluginConnection
from unittest.mock import Mock


class _Importer:
    async def parse(self, paths):  # type: ignore[no-untyped-def]
        return HistoryImportParseResult(sources=[])


def test_registrar_publishes_and_unloads_history_importer_contribution(tmp_path) -> None:
    registry = HistoryImporterRegistry()
    importer = _Importer()

    class _Plugin(Plugin):
        def get_history_importers(self):  # type: ignore[no-untyped-def]
            return [
                (
                    "archive",
                    importer,
                    HistoryImporterSpec(
                        importer_id="archive",
                        display_name="Archive",
                        accepted_extensions=["zip"],
                        format_version="1",
                    ),
                )
            ]

    registrar = PluginContributionRegistrar(
        tool_registry=type(
            "ToolRegistryStub",
            (),
            {"register": lambda *args: None, "unregister": lambda *args: None},
        )(),
        source_registry=SourceRegistry(),
        history_importer_registry=registry,
        hook_registry_provider=lambda: None,
    )
    manifest = PluginManifest(
        id="example",
        name="Example",
        version="1.0.0",
        source="external",
        contribution_types=[ContributionType.HISTORY_IMPORTER],
    )
    connection = PluginConnection(
        connection_id="archive-account",
        plugin_id="example",
        display_name="Archive",
        enabled=True,
    )
    context = PluginContext(connection, tmp_path / "state", tmp_path / "resources", Mock())
    plugin = _Plugin()
    plugin.configure(manifest=manifest, connection=connection, context=context)
    contributions = registrar.register(
        plugin_id="example",
        connection_id=connection.connection_id,
        manifest=manifest,
        plugin_instance=plugin,
    )

    assert [item.contribution_type for item in contributions] == [ContributionType.HISTORY_IMPORTER]
    assert (
        registry.get("example", "archive", connection_id=connection.connection_id).importer
        is importer
    )
    registrar.unregister(connection.connection_id)
    assert registry.get("example", "archive", connection_id=connection.connection_id) is None
