"""Schema validation prevents form bypass and ambiguous setting paths."""

import pytest
from magi_plugin_sdk.contracts import ExtensionFieldSpec
from magi_plugin_sdk.runtime import PluginConnection
from magi.plugins.connection_settings import validate_connection_settings


def connection(settings, **kwargs):
    return PluginConnection(connection_id="connection", plugin_id="example", display_name="Work", settings=settings, **kwargs)


def test_strict_nested_types_ranges_and_required_credentials():
    fields = [ExtensionFieldSpec(key="source.interval", label="Interval", type="number", minimum=1, maximum=60),
              ExtensionFieldSpec(key="active", label="Active", type="switch"),
              ExtensionFieldSpec(key="folders", label="Folders", type="path", default=[]),
              ExtensionFieldSpec(key="token", label="Token", type="secret", required=True)]
    settings = {"source": {"interval": 30}, "active": True, "folders": ["/one", "/two"]}
    validate_connection_settings(connection(settings), fields)
    validate_connection_settings(connection(settings, enabled=True, credential_refs={"token": "ref"}), fields)
    with pytest.raises(ValueError, match="missing"):
        validate_connection_settings(connection(settings, enabled=True), fields)
    for value in [True, "10", -1, 100, float("inf")]:
        with pytest.raises(ValueError):
            validate_connection_settings(connection({"source": {"interval": value}}), fields)


def test_duplicate_flat_and_nested_paths_and_secrets_are_rejected():
    field = ExtensionFieldSpec(key="source.interval", label="Interval", type="number")
    with pytest.raises(ValueError, match="ambiguous"):
        validate_connection_settings(connection({"source.interval": 2, "source": {"interval": 3}}), [field])
    with pytest.raises(ValueError, match="Secret"):
        validate_connection_settings(connection({"api_key": "value"}), [ExtensionFieldSpec(key="api_key", label="Key")])


def test_select_values_and_list_item_types_are_validated():
    fields = [ExtensionFieldSpec(key="mode", label="Mode", type="select", options=[{"label": "One", "value": "one"}]),
              ExtensionFieldSpec(key="tags", label="Tags", type="tags")]
    for settings in [{"mode": "unknown"}, {"tags": [1]}, {"tags": "value"}]:
        with pytest.raises(ValueError):
            validate_connection_settings(connection(settings), fields)
