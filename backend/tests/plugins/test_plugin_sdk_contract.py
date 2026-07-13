from __future__ import annotations

import pytest

from magi.plugins import Plugin
from magi_plugin_sdk import (
    DerivedAssertionRuleSpec,
    ExtractionProfileSpec,
    PluginI18n,
    PluginSettingsActionResult,
    TemporalSummaryFeatureBudget,
    TemporalSummarySourceFeatures,
    set_current_language,
)


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
        "get_settings_actions",
        "start_settings_action",
        "poll_settings_action",
        "cancel_settings_action",
        "build_temporal_summary_features",
        "get_extraction_profiles",
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
    assert plugin.get_settings_actions() == []
    assert plugin.build_temporal_summary_features(
        source_type="example",
        events=[],
        summary_category="day",
        period_start=0.0,
        period_end=1.0,
        budget=TemporalSummaryFeatureBudget(source_type="example"),
    ) is None
    assert plugin.get_extraction_profiles() == []
    assert plugin.get_plugin_ingress_registrations(runtime_paths=object()) == []

    with pytest.raises(KeyError):
        plugin.read_settings_resource("missing")

    with pytest.raises(KeyError):
        import asyncio

        asyncio.run(plugin.start_settings_action("missing", session_id="session-1"))

    with pytest.raises(KeyError):
        import asyncio

        asyncio.run(plugin.poll_settings_action("missing", session_id="session-1"))

    with pytest.raises(KeyError):
        import asyncio

        asyncio.run(plugin.cancel_settings_action("missing", session_id="session-1"))


def test_plugin_settings_action_result_contract_is_public() -> None:
    result = PluginSettingsActionResult(
        status="pending",
        message="Scan the QR code.",
        data={"qr_code_url": "data:image/png;base64,abc"},
        settings_updates={"account_id": "example"},
    )

    assert result.status == "pending"
    assert result.model_dump()["settings_updates"]["account_id"] == "example"


def test_plugin_i18n_defaults_to_current_language(tmp_path) -> None:
    i18n_dir = tmp_path / "i18n"
    i18n_dir.mkdir()
    (i18n_dir / "en.json").write_text('{"weixin": {"name": "Weixin"}}', encoding="utf-8")
    (i18n_dir / "zh-CN.json").write_text('{"weixin": {"name": "微信"}}', encoding="utf-8")

    try:
        set_current_language("zh-CN")
        assert PluginI18n("weixin", tmp_path).t("weixin.name") == "微信"
    finally:
        set_current_language(None)


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


def test_extraction_profile_spec_contract_is_public() -> None:
    spec = ExtractionProfileSpec(
        profile_id="source.example",
        source_types=["example"],
        allowed_entity_types=["software"],
        allowed_predicates=["USES"],
        allow_assertion=False,
        extraction_instructions="Treat example events as source-owned observations.",
    )

    dumped = spec.model_dump()
    assert dumped["profile_id"] == "source.example"
    assert dumped["source_types"] == ["example"]
    assert dumped["allowed_predicates"] == ["USES"]


def test_derived_assertion_rule_contract_exposes_safe_promotion_semantics() -> None:
    rule = DerivedAssertionRuleSpec(
        rule_id="coding.projects",
        source_predicates=["CONTRIBUTES_TO"],
        source_types=["coding_agent_history"],
        trait_family="project_profile",
        trait_name_template="project.{object_slug}",
        signal_preset="sustained_engagement",
        durable_permitted=True,
    )

    assert rule.min_observations == 3
    assert rule.min_distinct_days == 2
    assert rule.durable_min_observations == 6

    with pytest.raises(ValueError, match="passive_exposure"):
        DerivedAssertionRuleSpec(
            rule_id="browser.interests",
            source_predicates=["INTERESTED_IN"],
            source_types=["chrome_history"],
            trait_family="interest_profile",
            trait_name_template="interest.{object_slug}",
            signal_preset="passive_exposure",
            durable_permitted=True,
        )
