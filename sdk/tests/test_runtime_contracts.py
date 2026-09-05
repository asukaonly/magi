"""Contract tests for independent plugin connections and wire messages."""

import pytest
from pydantic import ValidationError

from magi_plugin_sdk.runtime import PluginConnection, PluginHandshake, SourceChange, SourceChangeBatch
from magi_plugin_sdk.contracts import ExtensionFieldSpec, ExtractionProfileSpec, PluginManifest


def test_connection_wire_round_trip_preserves_independent_identity():
    connection = PluginConnection(connection_id="work", plugin_id="mail", display_name="Work", settings={"folders": ["Inbox"]})
    assert PluginConnection.model_validate_json(connection.model_dump_json()) == connection
    assert connection.connection_id != connection.plugin_id


def test_protocol_mismatch_and_unknown_fields_fail_before_execution():
    payload = {"protocol_version": 2, "sdk_version": "0.2.0", "plugin_id": "mail", "connection_id": "work"}
    PluginHandshake.model_validate(payload)
    with pytest.raises(ValidationError):
        PluginHandshake.model_validate({**payload, "protocol_version": 1})
    with pytest.raises(ValidationError):
        PluginHandshake.model_validate({**payload, "authority": "admin"})


def test_source_change_preserves_delete_and_opaque_progress():
    batch = SourceChangeBatch(changes=[SourceChange(object_id="message/1", version="2", operation="delete")], next_cursor="opaque-progress")
    assert SourceChangeBatch.model_validate_json(batch.model_dump_json()) == batch


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_non_finite_source_time_is_rejected(value):
    with pytest.raises(ValidationError):
        SourceChange(object_id="1", version="1", occurred_at=value)


def test_unsupported_plugin_declarations_cannot_disappear_silently():
    with pytest.raises(ValidationError):
        ExtractionProfileSpec(profile_id="source.example", assertion_mode="derived")
    with pytest.raises(ValidationError):
        PluginManifest(id="example", name="Example", version="1.0.0", min_sdk_version="anything")
    with pytest.raises(ValidationError):
        ExtensionFieldSpec(key="limit", label="Limit", type="number", min=1)


def test_numeric_field_bounds_survive_schema_serialization():
    field = ExtensionFieldSpec(key="limit", label="Limit", type="number", minimum=1, maximum=10)
    assert field.model_dump()["minimum"] == 1
    with pytest.raises(ValidationError):
        ExtensionFieldSpec(key="limit", label="Limit", type="number", minimum=10, maximum=1)
