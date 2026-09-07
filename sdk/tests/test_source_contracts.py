"""Versioned source changes retain semantic hints without implicit connection state."""

from pathlib import Path
from enum import IntEnum
from itertools import combinations
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
    assert first.changes[0].object_id == second.changes[0].object_id == source.source_item_identity({"id": "same"})
    assert first.changes[0].version != second.changes[0].version
    assert first.next_cursor == "opaque"
    assert first.complete is False


def test_composite_identity_keeps_delimiter_boundaries_in_change_batches():
    source = NotesSource()
    source.update_key_fields = ("first", "second")
    items = [{"first": "a:b", "second": "c"}, {"first": "a", "second": "b:c"}]
    batch = source.build_change_batch(items)
    assert batch.changes[0].object_id != batch.changes[1].object_id
    assert [change.payload for change in batch.changes] == items
    assert [change.object_id for change in batch.changes] == [source.source_item_identity(item) for item in items]


@pytest.mark.parametrize("left,right", list(combinations([1, "1", 1.0, True, "True", 0, False, "0", [1], {"value": 1}], 2)))
def test_identity_preserves_json_value_types(left, right):
    source = NotesSource()
    assert source.source_item_identity({"id": left}) != source.source_item_identity({"id": right})


@pytest.mark.parametrize("value", [None, "", " \t", [], {}])
def test_empty_identity_keys_fail_explicitly_in_batches(value):
    with pytest.raises(ValueError, match="identity field 'id' must not be empty"):
        NotesSource().build_change_batch([{"id": value}])


def test_missing_identity_component_cannot_collapse_to_an_empty_default():
    source = NotesSource()
    source.update_key_fields = ("first", "second")
    with pytest.raises(ValueError, match="identity field 'second' is missing"):
        source.build_change_batch([{"first": "a", "second": "b"}, {"first": "a"}])


@pytest.mark.parametrize("fields", [(), ("",), (" ",), (None,)])
def test_missing_or_empty_key_declarations_fail_explicitly(fields):
    source = NotesSource()
    source.update_key_fields = fields
    with pytest.raises(ValueError, match="Source identity"):
        source.source_item_identity({"": "value", " ": "value", None: "value"})


class NumericKey(IntEnum):
    ONE = 1


@pytest.mark.parametrize("value", [(1,), {1: "value"}, {"nested": (1,)}, b"1", {1}, NumericKey.ONE])
def test_identity_rejects_implicit_json_type_coercion(value):
    with pytest.raises(ValueError, match="JSON types"):
        NotesSource().source_item_identity({"id": value})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_identity_rejects_non_finite_numbers(value):
    with pytest.raises(ValueError):
        NotesSource().source_item_identity({"id": value})


def test_identity_is_stable_across_instances_and_object_order():
    item = {"id": {"name": "笔记:a", "parts": [1, True, None, {"a": 1, "b": 2}]}, "text": "original"}
    reordered = {"text": "edited", "id": {"parts": [1, True, None, {"b": 2, "a": 1}], "name": "笔记:a"}}
    source = NotesSource()
    before = source.source_item_identity(item)
    assert before == NotesSource().source_item_identity(reordered)
    assert len(before) == 64
    assert item["text"] == "original"


def test_identity_includes_field_names_and_declared_order():
    item = {"first": "a", "second": "a"}
    source = NotesSource()
    identities = []
    for fields in (("first",), ("second",), ("first", "second"), ("second", "first")):
        source.update_key_fields = fields
        identities.append(source.source_item_identity(item))
    assert len(set(identities)) == len(identities)


def test_change_batch_uses_custom_identity_without_default_keys():
    class NativeIdentitySource(NotesSource):
        update_key_fields = ()

        def source_item_identity(self, item):
            return item["native_id"]

    source = NativeIdentitySource()
    batch = source.build_change_batch([{"native_id": "provider:original-id", "text": "one"}])
    assert batch.changes[0].object_id == "provider:original-id"


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
