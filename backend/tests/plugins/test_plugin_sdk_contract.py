from __future__ import annotations

import pytest

from magi.plugins import Plugin
from magi_plugin_sdk import (
    ActivationFlowSpec,
    DerivedAssertionRuleSpec,
    ExtensionFieldSpec,
    PluginI18n,
    TemporalSummaryFeatureBudget,
    set_current_language,
)


class ExamplePlugin(Plugin):
    pass


def test_plugin_base_host_hooks_have_safe_defaults() -> None:
    plugin = ExamplePlugin()

    assert plugin.get_tools() == []
    assert plugin.get_sources() == []
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


def test_activation_flow_preserves_first_context_overrides() -> None:
    flow = ActivationFlowSpec(
        title="Connect source",
        enabled_key="sources.example.enabled",
        configured_key="sources.example.configured",
        first_context={
            "max_items_per_sync": 75,
            "settings_overrides": {
                "sources.example.lookback_days": 7,
            }
        },
    )

    dumped = flow.model_dump()

    assert dumped["first_context"]["max_items_per_sync"] == 75
    assert dumped["first_context"]["settings_overrides"] == {"sources.example.lookback_days": 7}


def test_path_field_preserves_native_picker_kind() -> None:
    field = ExtensionFieldSpec(
        key="sources.example.root",
        type="path",
        path_kind="directory",
        label="Root folder",
    )

    assert field.model_dump()["path_kind"] == "directory"


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
