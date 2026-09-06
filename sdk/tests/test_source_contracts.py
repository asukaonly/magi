"""Versioned source changes retain semantic hints without implicit connection state."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from magi_plugin_sdk.context import PluginContext
from magi_plugin_sdk.runtime import PluginConnection
from magi_plugin_sdk.sources import ScopedSourceRuntimePaths, Source, SourceOutput, SourceSyncContext


class NotesSource(Source):
    update_key_fields = ("id",)

    async def build_output(self, item):
        return self._build_output(
            source_item_id=item["id"],
            activity=self._build_activity(
                source=self._build_activity_facet(code="notes", i18n_key="notes", fallback="Notes"),
                action=self._build_activity_facet(code="write", i18n_key="write", fallback="Wrote"),
                qualifiers={"count": 3, "duration": 1.5, "active": True},
            ),
            narration=self._build_narration(body="A note"),
        )


def test_change_batch_detects_object_updates_and_preserves_opaque_cursor():
    source = NotesSource()
    first = source.build_change_batch([{"id": "same", "text": "one"}], next_cursor="opaque", complete=False)
    second = source.build_change_batch([{"id": "same", "text": "two"}])
    assert first.changes[0].object_id == second.changes[0].object_id == "same"
    assert first.changes[0].version != second.changes[0].version
    assert first.next_cursor == "opaque"
    assert first.complete is False


def test_context_requires_explicit_connection_and_scopes_state(tmp_path):
    paths = ScopedSourceRuntimePaths("one", "notes", tmp_path / "one")
    with pytest.raises(PermissionError):
        paths.plugin_cache_dir("another-plugin")
    assert paths.plugin_cache_dir("notes") == tmp_path / "one"
    with pytest.raises(TypeError):
        SourceSyncContext(source_type="notes", manual=True, last_cursor=None, last_success_at=None, limit=1, runtime_paths=paths)
    with pytest.raises(ValueError):
        ScopedSourceRuntimePaths("one", "notes", Path("relative"))


def test_source_binding_rejects_mismatched_host_identity(tmp_path):
    connection = PluginConnection(connection_id="one", plugin_id="notes", display_name="One")
    context = PluginContext(connection, tmp_path / "state", tmp_path / "resources", Mock())
    source = NotesSource()
    source.bind_plugin_context(connection=connection, context=context)
    assert source.connection == connection
    assert source.context == context
    with pytest.raises(ValueError):
        source.bind_plugin_context(connection=connection.model_copy(update={"connection_id": "two"}), context=context)


@pytest.mark.asyncio
async def test_activity_hint_scalars_survive_worker_serialization():
    output = await NotesSource().build_output({"id": "one"})
    assert SourceOutput.from_dict(output.to_dict()).activity.qualifiers == {"count": 3, "duration": 1.5, "active": True}
