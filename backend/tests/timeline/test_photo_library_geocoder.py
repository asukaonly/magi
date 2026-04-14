"""Tests for photo-library geocoder — grid index, lookup, batch, graceful degradation."""
from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Load geocoder module from plugin directory
_geocoder_path = Path(__file__).resolve().parents[3] / "plugins" / "photo-library" / "geocoder.py"
_spec = importlib.util.spec_from_file_location(
    "photo_library_geocoder",
    _geocoder_path,
    submodule_search_locations=[str(_geocoder_path.parent)],
)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

GeoResult = _mod.GeoResult
batch_lookup = _mod.batch_lookup
format_location = _mod.format_location
lookup = _mod.lookup
reset = _mod.reset
_haversine_km = _mod._haversine_km
_parse_csv = _mod._parse_csv
_GRID_RES = _mod._GRID_RES


@pytest.fixture(autouse=True)
def _reset_geocoder():
    """Reset the geocoder singleton state between tests."""
    reset()
    yield
    reset()


def _write_test_csv(path: Path, cities: list[tuple[str, float, float, str, str]]) -> None:
    """Write a minimal GeoNames-format TSV for testing.

    Each tuple: (name, lat, lon, country_code, admin1)
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        for i, (name, lat, lon, cc, admin1) in enumerate(cities):
            # GeoNames columns: 0=id, 1=name, 2=ascii, 3=alt, 4=lat, 5=lon,
            # 6=feat_class, 7=feat_code, 8=cc, 9=cc2, 10=admin1, ...
            row = [
                str(1000 + i),  # geonameid
                name,           # name
                name,           # asciiname
                "",             # alternatenames
                str(lat),       # latitude
                str(lon),       # longitude
                "P",            # feature class
                "PPL",          # feature code
                cc,             # country code
                "",             # cc2
                admin1,         # admin1 code
                "",             # admin2
                "",             # admin3
                "",             # admin4
                "100000",       # population
                "",             # elevation
                "",             # dem
                "Asia/Tokyo",   # timezone
                "2024-01-01",   # modification date
            ]
            writer.writerow(row)


# ---------------------------------------------------------------------------
# Haversine
# ---------------------------------------------------------------------------

class TestHaversine:
    def test_same_point_is_zero(self):
        assert _haversine_km(35.0, 139.0, 35.0, 139.0) == 0.0

    def test_known_distance(self):
        # Tokyo to Osaka ≈ 400 km
        d = _haversine_km(35.6762, 139.6503, 34.6937, 135.5023)
        assert 380 < d < 420

    def test_antipodal(self):
        # Should be roughly half Earth circumference
        d = _haversine_km(0, 0, 0, 180)
        assert 20000 < d < 20100


# ---------------------------------------------------------------------------
# CSV parsing & grid index
# ---------------------------------------------------------------------------

class TestParseCSV:
    def test_parses_cities(self, tmp_path: Path):
        csv_path = tmp_path / "cities1000.txt"
        _write_test_csv(csv_path, [
            ("Tokyo", 35.6762, 139.6503, "JP", "40"),
            ("Osaka", 34.6937, 135.5023, "JP", "27"),
            ("Beijing", 39.9042, 116.4074, "CN", "22"),
        ])
        cities, grid = _parse_csv(csv_path)
        assert len(cities) == 3
        assert cities[0].name == "Tokyo"
        assert cities[2].country_code == "CN"
        # Grid should have entries
        assert len(grid) > 0

    def test_empty_file(self, tmp_path: Path):
        csv_path = tmp_path / "cities1000.txt"
        csv_path.write_text("")
        cities, grid = _parse_csv(csv_path)
        assert cities == []
        assert grid == {}


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

class TestLookup:
    def test_finds_nearest_city(self, tmp_path: Path):
        csv_path = tmp_path / "cities1000.txt"
        _write_test_csv(csv_path, [
            ("Tokyo", 35.6762, 139.6503, "JP", "40"),
            ("Osaka", 34.6937, 135.5023, "JP", "27"),
        ])

        # Pre-load by parsing + injecting into module globals
        _mod._cities, _mod._grid = _parse_csv(csv_path)

        result = lookup(35.7, 139.7, tmp_path)
        assert result is not None
        assert result.name == "Tokyo"

    def test_returns_none_when_download_fails(self, tmp_path: Path):
        # Simulate network failure — should return None gracefully
        with patch.object(_mod.urllib.request, "urlretrieve", side_effect=OSError("no network")):
            result = lookup(35.0, 139.0, tmp_path / "no_data")
        assert result is None

    def test_distinct_results_for_distant_points(self, tmp_path: Path):
        csv_path = tmp_path / "cities1000.txt"
        _write_test_csv(csv_path, [
            ("Tokyo", 35.6762, 139.6503, "JP", "40"),
            ("Beijing", 39.9042, 116.4074, "CN", "22"),
        ])
        _mod._cities, _mod._grid = _parse_csv(csv_path)

        tokyo = lookup(35.7, 139.7, tmp_path)
        beijing = lookup(40.0, 116.4, tmp_path)
        assert tokyo is not None and tokyo.name == "Tokyo"
        assert beijing is not None and beijing.name == "Beijing"


class TestBatchLookup:
    def test_batch_returns_correct_length(self, tmp_path: Path):
        csv_path = tmp_path / "cities1000.txt"
        _write_test_csv(csv_path, [
            ("Tokyo", 35.6762, 139.6503, "JP", "40"),
        ])
        _mod._cities, _mod._grid = _parse_csv(csv_path)

        results = batch_lookup(
            [(35.7, 139.7), (36.0, 140.0), (34.0, 135.0)],
            tmp_path,
        )
        assert len(results) == 3

    def test_batch_empty_returns_empty(self, tmp_path: Path):
        assert batch_lookup([], tmp_path) == []

    def test_batch_graceful_when_download_fails(self, tmp_path: Path):
        with patch.object(_mod.urllib.request, "urlretrieve", side_effect=OSError("no network")):
            results = batch_lookup(
                [(35.0, 139.0)],
                tmp_path / "no_data",
            )
        assert results == [None]


# ---------------------------------------------------------------------------
# Format
# ---------------------------------------------------------------------------

class TestFormatLocation:
    def test_basic_format(self):
        result = GeoResult(
            name="Shibuya", admin1="40", country_code="JP",
            latitude=35.6, longitude=139.7,
        )
        formatted = format_location(result)
        assert "Shibuya" in formatted
        assert "JP" in formatted

    def test_none_returns_empty(self):
        assert format_location(None) == ""

    def test_locale_map_override(self):
        result = GeoResult(
            name="Chaoyang", admin1="22", country_code="CN",
            latitude=39.9, longitude=116.4,
        )
        locale_map = {"CN:22": "北京"}
        formatted = format_location(result, locale_map=locale_map)
        assert "北京" in formatted
        assert "Chaoyang" in formatted

    def test_locale_map_miss_falls_back(self):
        result = GeoResult(
            name="Shibuya", admin1="40", country_code="JP",
            latitude=35.6, longitude=139.7,
        )
        locale_map = {"CN:22": "北京"}
        formatted = format_location(result, locale_map=locale_map)
        assert "Shibuya" in formatted
        assert "40" in formatted  # admin1 in fallback


# ---------------------------------------------------------------------------
# Data availability check
# ---------------------------------------------------------------------------

class TestDataAvailability:
    def test_not_available_when_no_file(self, tmp_path: Path):
        assert _mod.is_data_available(tmp_path) is False

    def test_available_when_csv_exists(self, tmp_path: Path):
        (tmp_path / "cities1000.txt").write_text("test")
        assert _mod.is_data_available(tmp_path) is True
