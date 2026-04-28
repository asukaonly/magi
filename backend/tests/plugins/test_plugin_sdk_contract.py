from __future__ import annotations

import pytest

from magi.plugins import Plugin
from magi_plugin_sdk import TemporalSummaryFeatureBudget, TemporalSummarySourceFeatures


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
        budget=TemporalSummaryFeatureBudget(source_type="example"),
    ) is None
    assert plugin.get_plugin_ingress_registrations(runtime_paths=object()) == []

    with pytest.raises(KeyError):
        plugin.read_settings_resource("missing")


def test_temporal_summary_feature_contracts_are_public() -> None:
    budget = TemporalSummaryFeatureBudget(
        source_type="music",
        total_event_count=20,
        available_event_count=10,
        selected_event_count=4,
    )
    features = TemporalSummarySourceFeatures(
        source_type="music",
        total_event_count=20,
        covered_event_count=10,
        omitted_event_count=10,
        coverage_ratio=0.5,
        summary_lines=["Listening concentrated in j-pop."],
        representative_event_ids=["evt-1"],
    )

    assert budget.selection_policy == "source_aware_compaction_v1"
    assert features.model_dump()["source_type"] == "music"
