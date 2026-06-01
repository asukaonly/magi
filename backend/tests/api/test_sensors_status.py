"""Tests for plugin-i18n translation augmentation on /sensors/status.

These tests exercise the helpers added in Phase 1 of the plugin-i18n refactor:
the ``*_translated`` fields backed by each plugin's own ``i18n/<lang>.json``.
"""
from __future__ import annotations

from typing import Any

import pytest

from magi.api.routers.plugins_common import (
    _serialize_activation_flow,
    _serialize_field,
    _serialize_settings_action,
    _serialize_settings_ui_block,
    normalize_plugin_id,
    translate_with_fallback,
)
from magi.plugins.contracts import ExtensionFieldOption, ExtensionFieldSpec


class _FakeI18n:
    """Minimal PluginI18n stand-in that looks up a flat dict."""

    def __init__(self, translations: dict[str, str]) -> None:
        self._translations = dict(translations)

    def t(self, key: str, fallback: Any = None, **kwargs: Any) -> Any:
        value = self._translations.get(key)
        if value is None:
            return fallback
        if kwargs:
            try:
                return value.format(**kwargs)
            except KeyError:
                return value
        return value


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def test_normalize_plugin_id_replaces_hyphens_with_underscores() -> None:
    assert normalize_plugin_id("chrome-history") == "chrome_history"
    assert normalize_plugin_id("git_activity") == "git_activity"
    assert normalize_plugin_id("calendar") == "calendar"


def test_translate_with_fallback_returns_value_when_present() -> None:
    i18n = _FakeI18n({"chrome_history.name": "Chrome 历史"})
    assert (
        translate_with_fallback(i18n, "chrome_history.name", "Chrome History")
        == "Chrome 历史"
    )


def test_translate_with_fallback_returns_fallback_on_missing_key() -> None:
    i18n = _FakeI18n({})
    assert (
        translate_with_fallback(i18n, "chrome_history.name", "Chrome History")
        == "Chrome History"
    )


def test_translate_with_fallback_tolerates_none_i18n() -> None:
    assert translate_with_fallback(None, "x.y", "fallback") == "fallback"


def test_translate_with_fallback_swallows_i18n_errors() -> None:
    class BrokenI18n:
        def t(self, *args: Any, **kwargs: Any) -> str:
            raise RuntimeError("boom")

    assert translate_with_fallback(BrokenI18n(), "x.y", "fb") == "fb"


# ──────────────────────────────────────────────────────────────────────
# _serialize_field
# ──────────────────────────────────────────────────────────────────────


def test_serialize_field_adds_translated_mirrors_for_label_and_description() -> None:
    field = ExtensionFieldSpec(
        key="sensors.chrome_history.profile",
        type="input",
        label="Profile",
        description="Chrome profile directory.",
        surface="timeline",
    )
    i18n = _FakeI18n(
        {
            "chrome_history.fields.profile.label": "配置文件",
            "chrome_history.fields.profile.description": "Chrome 配置目录。",
        }
    )

    serialized = _serialize_field(
        field, i18n, contribution_id="timeline.chrome_history", plugin_id="chrome-history"
    )

    assert serialized["label_translated"] == "配置文件"
    assert serialized["description_translated"] == "Chrome 配置目录。"
    # Legacy fields preserved (i18n missing → fallback).
    assert serialized["label"] == "Profile"
    assert serialized["description"] == "Chrome profile directory."


def test_serialize_field_falls_back_to_raw_when_translation_missing() -> None:
    field = ExtensionFieldSpec(
        key="sensors.chrome_history.profile",
        type="input",
        label="Profile",
        description="Chrome profile directory.",
        surface="timeline",
    )
    i18n = _FakeI18n({})

    serialized = _serialize_field(
        field, i18n, contribution_id="timeline.chrome_history", plugin_id="chrome-history"
    )

    assert serialized["label_translated"] == "Profile"
    assert serialized["description_translated"] == "Chrome profile directory."


def test_serialize_field_translates_options_via_plugin_i18n() -> None:
    field = ExtensionFieldSpec(
        key="sensors.chrome_history.sync_mode",
        type="select",
        label="Sync Mode",
        description="",
        surface="timeline",
        options=[
            ExtensionFieldOption(label="Manual", value="manual"),
            ExtensionFieldOption(label="Interval", value="interval"),
        ],
    )
    i18n = _FakeI18n(
        {
            "chrome_history.options.sync_mode.manual": "手动",
            "chrome_history.options.sync_mode.interval": "定时",
        }
    )

    serialized = _serialize_field(
        field, i18n, contribution_id="timeline.chrome_history", plugin_id="chrome-history"
    )

    assert [opt["label_translated"] for opt in serialized["options"]] == [
        "手动",
        "定时",
    ]


def test_serialize_field_without_plugin_id_omits_translated_fields() -> None:
    field = ExtensionFieldSpec(
        key="sensors.chrome_history.profile",
        type="input",
        label="Profile",
        description="",
        surface="timeline",
    )
    i18n = _FakeI18n({})

    serialized = _serialize_field(field, i18n, contribution_id="timeline.chrome_history")

    assert "label_translated" not in serialized
    assert "description_translated" not in serialized


# ──────────────────────────────────────────────────────────────────────
# _serialize_settings_action
# ──────────────────────────────────────────────────────────────────────


def test_serialize_settings_action_adds_plugin_scoped_translations() -> None:
    action = {
        "action_id": "request_auth",
        "label": "Request access",
        "description": "Open System Settings to grant Screen Recording.",
        "button_label": "Open",
    }
    i18n = _FakeI18n(
        {
            "screen_time.actions.request_auth.label": "申请权限",
            "screen_time.actions.request_auth.description": "在系统设置中授予录屏权限。",
            "screen_time.actions.request_auth.button_label": "打开",
        }
    )

    serialized = _serialize_settings_action(action, i18n, plugin_id="screen-time")

    assert serialized["label_translated"] == "申请权限"
    assert serialized["description_translated"] == "在系统设置中授予录屏权限。"
    assert serialized["button_label_translated"] == "打开"


# ──────────────────────────────────────────────────────────────────────
# _serialize_settings_ui_block
# ──────────────────────────────────────────────────────────────────────


def test_serialize_settings_ui_block_adds_title_and_description_translations() -> None:
    block = {
        "block_id": "permission_status",
        "title": "Permissions",
        "description": "macOS permissions required.",
    }
    i18n = _FakeI18n(
        {
            "screen_time.ui_blocks.permission_status.title": "权限",
            "screen_time.ui_blocks.permission_status.description": "需要的 macOS 权限。",
        }
    )

    serialized = _serialize_settings_ui_block(block, i18n, plugin_id="screen-time")

    assert serialized["title_translated"] == "权限"
    assert serialized["description_translated"] == "需要的 macOS 权限。"


# ──────────────────────────────────────────────────────────────────────
# _serialize_activation_flow
# ──────────────────────────────────────────────────────────────────────


def test_serialize_activation_flow_translates_four_keys() -> None:
    flow = {
        "title": "Enable Chrome History",
        "description": "Privacy notice.",
        "confirm_label": "Enable",
        "cancel_label": "Not now",
    }
    i18n = _FakeI18n(
        {
            "chrome_history.activation.title": "启用 Chrome 历史",
            "chrome_history.activation.description": "隐私提示。",
            "chrome_history.activation.confirm_label": "启用",
            "chrome_history.activation.cancel_label": "暂不",
        }
    )

    serialized = _serialize_activation_flow(flow, i18n, plugin_id="chrome-history")

    assert serialized["title_translated"] == "启用 Chrome 历史"
    assert serialized["description_translated"] == "隐私提示。"
    assert serialized["confirm_label_translated"] == "启用"
    assert serialized["cancel_label_translated"] == "暂不"


def test_serialize_activation_flow_falls_back_to_raw_when_keys_missing() -> None:
    flow = {
        "title": "Enable Chrome History",
        "description": "",
        "confirm_label": "Enable",
        "cancel_label": "Not now",
    }
    i18n = _FakeI18n({})

    serialized = _serialize_activation_flow(flow, i18n, plugin_id="chrome-history")

    # When the translation is missing, the *_translated mirror falls back to
    # the raw English value passed through ``fallback``.
    assert serialized["title_translated"] == "Enable Chrome History"
    assert serialized["confirm_label_translated"] == "Enable"
    assert serialized["cancel_label_translated"] == "Not now"
