from __future__ import annotations

import pytest

from magi.plugins import Plugin


class ExamplePlugin(Plugin):
    pass


def test_plugin_base_exposes_host_runtime_hooks() -> None:
    required_hooks = [
        "get_tools",
        "get_sensors",
        "get_channel",
        "get_channel_fields",
        "get_settings_resources",
        "read_settings_resource",
        "build_temporal_summary_features",
        "get_plugin_ingress_registrations",
    ]

    for hook in required_hooks:
        assert hasattr(Plugin, hook), hook


def test_plugin_base_host_hooks_have_safe_defaults() -> None:
    plugin = ExamplePlugin()

    assert plugin.get_tools() == []
    assert plugin.get_sensors() == []
    assert plugin.get_channel() is None
    assert plugin.get_channel_fields() == []
    assert plugin.get_settings_resources() == []
    assert plugin.build_temporal_summary_features(
        source_type="example",
        events=[],
        summary_category="day",
        period_start=0.0,
        period_end=1.0,
    ) is None
    assert plugin.get_plugin_ingress_registrations(runtime_paths=object()) == []

    with pytest.raises(KeyError):
        plugin.read_settings_resource("missing")