"""Tests for locale data mappings."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Load modules from plugin directory
_plugin_dir = Path(__file__).resolve().parents[3] / "plugins" / "photo-library"

_geocoder_path = _plugin_dir / "geocoder.py"
_geo_spec = importlib.util.spec_from_file_location(
    "photo_library_geocoder",
    _geocoder_path,
    submodule_search_locations=[str(_plugin_dir)],
)
assert _geo_spec is not None and _geo_spec.loader is not None
_geo_mod = importlib.util.module_from_spec(_geo_spec)
sys.modules[_geo_spec.name] = _geo_mod
_geo_spec.loader.exec_module(_geo_mod)

GeoResult = _geo_mod.GeoResult
format_location = _geo_mod.format_location

_locale_path = _plugin_dir / "locale_data.py"
_locale_spec = importlib.util.spec_from_file_location(
    "photo_library_locale_data",
    _locale_path,
    submodule_search_locations=[str(_plugin_dir)],
)
assert _locale_spec is not None and _locale_spec.loader is not None
_locale_mod = importlib.util.module_from_spec(_locale_spec)
sys.modules[_locale_spec.name] = _locale_mod
_locale_spec.loader.exec_module(_locale_mod)

LOCALE_MAPS = _locale_mod.LOCALE_MAPS
get_locale_map = _locale_mod.get_locale_map


class TestLocaleData:
    """Tests for locale mapping retrieval and format_location integration."""

    def test_zh_cn_map_exists(self):
        m = get_locale_map("zh-CN")
        assert m is not None
        assert len(m) > 30  # Should have many entries

    def test_zh_shortcut(self):
        assert get_locale_map("zh") is get_locale_map("zh-CN")

    def test_unknown_locale_returns_none(self):
        assert get_locale_map("fr") is None
        assert get_locale_map("de-DE") is None

    def test_cn_provinces_covered(self):
        m = get_locale_map("zh-CN")
        assert m is not None
        assert "CN:22" in m  # Beijing
        assert "CN:23" in m  # Shanghai
        assert "CN:30" in m  # Guangdong
        assert "CN:04" in m  # Zhejiang

    def test_format_location_with_locale_map(self):
        geo = GeoResult(
            name="Beijing",
            admin1="22",
            country_code="CN",
            latitude=39.9,
            longitude=116.4,
        )
        m = get_locale_map("zh-CN")
        result = format_location(geo, locale_map=m)
        assert "北京" in result
        assert "Beijing" in result

    def test_format_location_without_matching_locale(self):
        geo = GeoResult(
            name="Springfield",
            admin1="IL",
            country_code="US",
            latitude=39.8,
            longitude=-89.6,
        )
        m = get_locale_map("zh-CN")
        # US:IL is in the map
        result = format_location(geo, locale_map=m)
        assert "伊利诺伊" in result

    def test_format_location_fallback_for_unmapped_region(self):
        geo = GeoResult(
            name="SomeCity",
            admin1="ZZ",
            country_code="XX",
            latitude=0.0,
            longitude=0.0,
        )
        m = get_locale_map("zh-CN")
        result = format_location(geo, locale_map=m)
        # Should fall back to English: "SomeCity, ZZ, XX"
        assert "SomeCity" in result
        assert "XX" in result
