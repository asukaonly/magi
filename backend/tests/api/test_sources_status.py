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


@pytest.mark.parametrize(
    "catalog,expected",
    [
        ({"chrome_history.name": "Chrome 历史"}, "Chrome 历史"),
        ({}, "Chrome History"),
        (None, "Chrome History"),
    ],
)
def test_translation_uses_available_value_or_fallback(catalog, expected) -> None:
    i18n = _FakeI18n(catalog) if catalog is not None else None
    assert translate_with_fallback(i18n, "chrome_history.name", "Chrome History") == expected


def test_translate_with_fallback_swallows_i18n_errors() -> None:
    class BrokenI18n:
        def t(self, *args: Any, **kwargs: Any) -> str:
            raise RuntimeError("boom")

    assert translate_with_fallback(BrokenI18n(), "x.y", "fb") == "fb"


# ──────────────────────────────────────────────────────────────────────
# _serialize_field
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("translated", [False, True])
def test_field_serialization_preserves_raw_copy_and_translates_when_available(translated) -> None:
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

    if not translated:
        i18n = _FakeI18n({})

    serialized = _serialize_field(
        field, i18n, contribution_id="timeline.chrome_history", plugin_id="chrome-history"
    )

    assert serialized["label_translated"] == ("配置文件" if translated else "Profile")
    assert serialized["description_translated"] == (
        "Chrome 配置目录。" if translated else "Chrome profile directory."
    )
    # Legacy fields preserved (i18n missing → fallback).
    assert serialized["label"] == "Profile"
    assert serialized["description"] == "Chrome profile directory."


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


@pytest.mark.parametrize("translated", [False, True])
def test_layout_translation_preserves_tab_identity_and_availability(translated) -> None:
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

    if not translated:
        i18n = _FakeI18n({})

    serialized = _serialize_settings_layout(layout, i18n, plugin_id="photo-library")

    assert serialized["tabs"][0]["label_translated"] == (
        "本地照片" if translated else "Local Photos"
    )
    assert serialized["tabs"][0]["description_translated"] == (
        "扫描本地照片文件夹。" if translated else "Scan folders."
    )
    assert serialized["tabs"][1]["unavailable_reason_translated"] == (
        "Apple Photos 仅在 macOS 上可用。"
        if translated
        else "Apple Photos is only available on macOS."
    )

    for original, serialized_tab in zip(layout["tabs"], serialized["tabs"], strict=True):
        assert {key: serialized_tab[key] for key in original} == original


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


@pytest.mark.parametrize("translated", [False, True])
def test_activation_flow_translates_top_level_and_nested_copy_together(translated) -> None:
    """Embedded activation-flow fields get the same plugin-scoped ``*_translated``
    mirrors that :func:`_serialize_field` produces for top-level fields, so the
    activation dialog can render localized labels / descriptions / option labels.
    """
    flow = {
        "title": "Enable Chrome History",
        "description": "Privacy notice.",
        "confirm_label": "Enable",
        "cancel_label": "Not now",
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
            "chrome_history.activation.title": "启用 Chrome 历史",
            "chrome_history.activation.description": "隐私提示。",
            "chrome_history.activation.confirm_label": "启用",
            "chrome_history.activation.cancel_label": "暂不",
            "chrome_history.fields.initial_sync_policy.label": "首次同步范围",
            "chrome_history.fields.initial_sync_policy.description": "决定首次导入多少历史。",
            "chrome_history.options.initial_sync_policy.full": "同步全部历史",
            "chrome_history.options.initial_sync_policy.lookback_days": "同步最近几天",
            "chrome_history.fields.initial_sync_lookback_days.label": "最近天数",
            "chrome_history.fields.initial_sync_lookback_days.description": "当范围设为最近几天时使用。",
        }
    )

    if not translated:
        i18n = _FakeI18n({})

    serialized = _serialize_activation_flow(flow, i18n, plugin_id="chrome-history")

    fields = serialized["fields"]
    assert fields[0]["label_translated"] == ("首次同步范围" if translated else "First Sync Scope")
    assert fields[0]["description_translated"] == (
        "决定首次导入多少历史。" if translated else "Decide how much history to import."
    )
    assert [opt["label_translated"] for opt in fields[0]["options"]] == (
        ["同步全部历史", "同步最近几天"]
        if translated
        else ["Sync full history", "Sync recent days"]
    )
    # Raw label preserved as fallback for the frontend's ``label_translated || label``.
    assert fields[0]["label"] == "First Sync Scope"
    assert fields[1]["label_translated"] == ("最近天数" if translated else "Recent Days")
    assert fields[1]["description_translated"] == (
        "当范围设为最近几天时使用。" if translated else "Used when scope is recent days."
    )

    for field, localized in {
        "title": "启用 Chrome 历史",
        "description": "隐私提示。",
        "confirm_label": "启用",
        "cancel_label": "暂不",
    }.items():
        assert serialized[field] == flow[field]
        assert serialized[field + "_translated"] == (localized if translated else flow[field])
    assert [option["value"] for option in fields[0]["options"]] == ["full", "lookback_days"]
    assert [field["key"] for field in fields] == [
        "sources.chrome_history.initial_sync_policy",
        "sources.chrome_history.initial_sync_lookback_days",
    ]


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
