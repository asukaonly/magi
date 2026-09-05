"""Tests for plugin-i18n translation augmentation on /sources/status.

These tests exercise the helpers added in Phase 1 of the plugin-i18n refactor:
the ``*_translated`` fields backed by each plugin's own ``i18n/<lang>.json``.
"""
from __future__ import annotations

from typing import Any

import pytest

from magi.api.routers.plugins_common import (
    _serialize_activation_flow,
    _serialize_source_capability,
    _serialize_field,
    _serialize_settings_action,
    _serialize_settings_layout,
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
        key="sources.chrome_history.profile",
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
        key="sources.chrome_history.profile",
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
        key="sources.chrome_history.sync_mode",
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
        key="sources.chrome_history.profile",
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
# _serialize_settings_layout
# ──────────────────────────────────────────────────────────────────────


def test_serialize_settings_layout_translates_tab_text() -> None:
    layout = {
        "kind": "tabs",
        "controller_key": "sources.photo_library.source_mode",
        "tabs": [
            {
                "tab_id": "directory",
                "value": "directory",
                "label": "Local Photos",
                "description": "Scan folders.",
                "available": True,
            },
            {
                "tab_id": "apple_photos",
                "value": "apple_photos",
                "label": "Apple Photos",
                "description": "Read Photos.",
                "available": False,
                "unavailable_reason": "Apple Photos is only available on macOS.",
            },
        ],
    }
    i18n = _FakeI18n(
        {
            "photo_library.settings_layout.tabs.directory.label": "本地照片",
            "photo_library.settings_layout.tabs.directory.description": "扫描本地照片文件夹。",
            "photo_library.settings_layout.tabs.apple_photos.label": "Apple Photos",
            "photo_library.settings_layout.tabs.apple_photos.description": "直接读取 macOS 照片图库。",
            "photo_library.settings_layout.tabs.apple_photos.unavailable_reason": "Apple Photos 仅在 macOS 上可用。",
        }
    )

    serialized = _serialize_settings_layout(layout, i18n, plugin_id="photo-library")

    assert serialized["tabs"][0]["label_translated"] == "本地照片"
    assert serialized["tabs"][0]["description_translated"] == "扫描本地照片文件夹。"
    assert serialized["tabs"][1]["unavailable_reason_translated"] == "Apple Photos 仅在 macOS 上可用。"


def test_serialize_settings_layout_falls_back_to_raw_tab_text() -> None:
    layout = {
        "kind": "tabs",
        "controller_key": "sources.photo_library.source_mode",
        "tabs": [
            {
                "tab_id": "apple_photos",
                "value": "apple_photos",
                "label": "Apple Photos",
                "description": "Read Photos.",
                "unavailable_reason": "Apple Photos is only available on macOS.",
            }
        ],
    }
    i18n = _FakeI18n({})

    serialized = _serialize_settings_layout(layout, i18n, plugin_id="photo-library")

    assert serialized["tabs"][0]["label_translated"] == "Apple Photos"
    assert serialized["tabs"][0]["description_translated"] == "Read Photos."
    assert serialized["tabs"][0]["unavailable_reason_translated"] == "Apple Photos is only available on macOS."


# ──────────────────────────────────────────────────────────────────────
# _serialize_source_capability
# ──────────────────────────────────────────────────────────────────────


def test_serialize_source_capability_adds_group_and_entry_translations() -> None:
    metadata = {
        "capability_id": "photo_library",
        "capability_display_name": "Photo Library",
        "capability_description": "Read Apple Photos or local folders.",
        "entry_id": "apple_photos",
    }
    i18n = _FakeI18n(
        {
            "photo_library.capabilities.photo_library.display_name": "照片库",
            "photo_library.capabilities.photo_library.description": "统一管理照片进入时间线的方式。",
            "photo_library.entries.apple_photos.display_name": "Apple Photos",
            "photo_library.entries.apple_photos.description": "直接读取 macOS 照片图库。",
        }
    )

    serialized = _serialize_source_capability(
        metadata,
        i18n,
        plugin_id="photo-library",
        fallback_source_name="photo_library_apple_photos",
        fallback_display_name="Apple Photos",
        fallback_description="Read Photos.",
    )

    assert serialized == {
        "capability_id": "photo_library",
        "capability_display_name": "Photo Library",
        "capability_display_name_translated": "照片库",
        "capability_description": "Read Apple Photos or local folders.",
        "capability_description_translated": "统一管理照片进入时间线的方式。",
        "entry_id": "apple_photos",
        "entry_display_name": "Apple Photos",
        "entry_display_name_translated": "Apple Photos",
        "entry_description": "Read Photos.",
        "entry_description_translated": "直接读取 macOS 照片图库。",
    }


def test_serialize_source_capability_uses_entry_translation_for_single_source_groups() -> None:
    metadata = {}
    i18n = _FakeI18n(
        {
            "screen_time.entries.screen_time.display_name": "应用使用",
            "screen_time.entries.screen_time.description": "统计前台应用的使用时长。",
        }
    )

    serialized = _serialize_source_capability(
        metadata,
        i18n,
        plugin_id="screen-time",
        fallback_source_name="screen_time",
        fallback_display_name="App Usage",
        fallback_description="Polls the foreground app.",
    )

    assert serialized["capability_display_name_translated"] == "应用使用"
    assert serialized["capability_description_translated"] == "统计前台应用的使用时长。"


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


def test_serialize_activation_flow_translates_embedded_fields() -> None:
    """Embedded activation-flow fields get the same plugin-scoped ``*_translated``
    mirrors that :func:`_serialize_field` produces for top-level fields, so the
    activation dialog can render localized labels / descriptions / option labels.
    """
    flow = {
        "title": "Enable Chrome History",
        "fields": [
            {
                "key": "sources.chrome_history.initial_sync_policy",
                "type": "select",
                "label": "First Sync Scope",
                "description": "Decide how much history to import.",
                "options": [
                    {"label": "Sync full history", "value": "full"},
                    {"label": "Sync recent days", "value": "lookback_days"},
                ],
            },
            {
                "key": "sources.chrome_history.initial_sync_lookback_days",
                "type": "number",
                "label": "Recent Days",
                "description": "Used when scope is recent days.",
            },
        ],
    }
    i18n = _FakeI18n(
        {
            "chrome_history.fields.initial_sync_policy.label": "首次同步范围",
            "chrome_history.fields.initial_sync_policy.description": "决定首次导入多少历史。",
            "chrome_history.options.initial_sync_policy.full": "同步全部历史",
            "chrome_history.options.initial_sync_policy.lookback_days": "同步最近几天",
            "chrome_history.fields.initial_sync_lookback_days.label": "最近天数",
            "chrome_history.fields.initial_sync_lookback_days.description": "当范围设为最近几天时使用。",
        }
    )

    serialized = _serialize_activation_flow(flow, i18n, plugin_id="chrome-history")

    fields = serialized["fields"]
    assert fields[0]["label_translated"] == "首次同步范围"
    assert fields[0]["description_translated"] == "决定首次导入多少历史。"
    assert [opt["label_translated"] for opt in fields[0]["options"]] == [
        "同步全部历史",
        "同步最近几天",
    ]
    # Raw label preserved as fallback for the frontend's ``label_translated || label``.
    assert fields[0]["label"] == "First Sync Scope"
    assert fields[1]["label_translated"] == "最近天数"
    assert fields[1]["description_translated"] == "当范围设为最近几天时使用。"


def test_serialize_activation_flow_embedded_fields_fall_back_to_raw() -> None:
    flow = {
        "title": "Enable Chrome History",
        "fields": [
            {
                "key": "sources.chrome_history.initial_sync_policy",
                "type": "select",
                "label": "First Sync Scope",
                "description": "Decide how much history to import.",
                "options": [{"label": "Sync full history", "value": "full"}],
            }
        ],
    }
    i18n = _FakeI18n({})

    serialized = _serialize_activation_flow(flow, i18n, plugin_id="chrome-history")

    field = serialized["fields"][0]
    assert field["label_translated"] == "First Sync Scope"
    assert field["description_translated"] == "Decide how much history to import."
    assert field["options"][0]["label_translated"] == "Sync full history"


def test_serialize_activation_flow_without_plugin_id_leaves_fields_untouched() -> None:
    flow = {
        "title": "Enable Chrome History",
        "fields": [
            {
                "key": "sources.chrome_history.initial_sync_policy",
                "label": "First Sync Scope",
            }
        ],
    }
    i18n = _FakeI18n({})

    serialized = _serialize_activation_flow(flow, i18n, plugin_id=None)

    assert "label_translated" not in serialized["fields"][0]
    assert "title_translated" not in serialized
