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


def test_setup_catalog_is_declarative_before_plugin_execution():
    manifest = PluginManifest(
        id="mail", name="Mail", version="1.0.0",
        settings_fields=[{"key": "token", "label": "Token", "type": "secret"}],
        settings_actions=[{"action_id": "login", "label": "Login", "requires_enabled": False}],
        settings_resources=[{"resource_name": "accounts", "requires_enabled": False}],
    )
    copy = PluginManifest.model_validate_json(manifest.model_dump_json())
    assert copy.settings_actions[0].requires_enabled is False
    assert copy.settings_resources[0].requires_enabled is False
    assert copy.settings_fields[0].type == "secret"


def test_nested_declarations_reject_typos_and_non_finite_bounds():
    with pytest.raises(ValidationError):
        PluginManifest(id="mail", name="Mail", version="1.0.0",
                       settings_actions=[{"action_id": "login", "label": "Login", "requires_enable": False}])
    with pytest.raises(ValidationError):
        ExtensionFieldSpec(key="limit", label="Limit", type="number", maximum=float("inf"))


def test_scoped_clear_cannot_impersonate_a_global_generation(tmp_path):
    from magi_plugin_sdk.user_content import UserContentClearRequest, UserContentClearContext
    from magi_plugin_sdk.sensors import ScopedSensorRuntimePaths

    request = UserContentClearRequest(connection_id="mail-work", reason="user_clear_connection_content")
    assert request.clear_generation is None
    paths = ScopedSensorRuntimePaths("mail-work", "mail", tmp_path)
    with pytest.raises(ValueError):
        UserContentClearContext(request=request, runtime_paths=paths, plugin_id="mail", connection_id="mail-personal")
    with pytest.raises(ValueError):
        UserContentClearRequest(connection_id="mail-work", clear_generation=1)
