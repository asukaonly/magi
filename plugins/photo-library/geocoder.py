"""Offline reverse geocoder using GeoNames cities1000 dataset.

Downloads the dataset on first use to ``~/.magi/cache/plugins/photo-library/``
and builds a grid-based spatial index for O(1) nearest-city lookups.
Zero external dependencies — pure Python with ``urllib`` + ``zipfile``.
"""
from __future__ import annotations

import csv
import io
import logging
import math
import os
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_GEONAMES_URL = "https://download.geonames.org/export/dump/cities1000.zip"
_CSV_FILENAME = "cities1000.txt"

# Grid resolution in degrees — 1° ≈ 111 km at the equator.
_GRID_RES = 1


@dataclass(slots=True)
class GeoResult:
    """Result of a reverse geocode lookup."""
    name: str
    admin1: str
    country_code: str
    latitude: float
    longitude: float


# ---------------------------------------------------------------------------
# Singleton state
# ---------------------------------------------------------------------------

_grid: dict[tuple[int, int], list[tuple[float, float, int]]] | None = None
_cities: list[GeoResult] | None = None


# ---------------------------------------------------------------------------
# Download & parse
# ---------------------------------------------------------------------------

def _ensure_csv(cache_dir: Path) -> Path:
    """Download and extract the GeoNames dataset if not already present."""
    csv_path = cache_dir / _CSV_FILENAME
    if csv_path.exists():
        return csv_path

    cache_dir.mkdir(parents=True, exist_ok=True)
    zip_path = cache_dir / "cities1000.zip"

    logger.info("Downloading GeoNames cities1000 dataset …")
    try:
        urllib.request.urlretrieve(_GEONAMES_URL, str(zip_path))  # noqa: S310
    except Exception:
        logger.warning("Failed to download GeoNames dataset", exc_info=True)
        if zip_path.exists():
            zip_path.unlink(missing_ok=True)
        raise

    with zipfile.ZipFile(zip_path) as zf:
        zf.extract(_CSV_FILENAME, cache_dir)
    zip_path.unlink(missing_ok=True)
    logger.info("GeoNames dataset ready at %s", csv_path)
    return csv_path


def _parse_csv(csv_path: Path) -> tuple[
    list[GeoResult],
    dict[tuple[int, int], list[tuple[float, float, int]]],
]:
    """Parse the GeoNames TSV file and build a grid index.

    GeoNames TSV columns (selected):
      0: geonameid, 1: name, 4: latitude, 5: longitude,
      8: country code, 10: admin1 code
    """
    cities: list[GeoResult] = []
    grid: dict[tuple[int, int], list[tuple[float, float, int]]] = {}

    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter="\t")
        for row in reader:
            if len(row) < 11:
                continue
            try:
                lat = float(row[4])
                lon = float(row[5])
            except (ValueError, IndexError):
                continue
            idx = len(cities)
            cities.append(GeoResult(
                name=row[1],
                admin1=row[10],
                country_code=row[8],
                latitude=lat,
                longitude=lon,
            ))
            cell = (int(math.floor(lat / _GRID_RES)), int(math.floor(lon / _GRID_RES)))
            grid.setdefault(cell, []).append((lat, lon, idx))

    return cities, grid


# ---------------------------------------------------------------------------
# Haversine distance (km)
# ---------------------------------------------------------------------------

_R_EARTH_KM = 6371.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Approximate great-circle distance in km."""
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return _R_EARTH_KM * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

def _load(cache_dir: Path) -> None:
    """Load and index the dataset (idempotent)."""
    global _grid, _cities  # noqa: PLW0603
    if _grid is not None:
        return
    csv_path = _ensure_csv(cache_dir)
    _cities, _grid = _parse_csv(csv_path)
    logger.info("GeoNames index loaded: %d cities", len(_cities))


def _nearest(lat: float, lon: float) -> GeoResult | None:
    """Find the nearest city to (lat, lon) using the grid index."""
    if _grid is None or _cities is None:
        return None
    cell_lat = int(math.floor(lat / _GRID_RES))
    cell_lon = int(math.floor(lon / _GRID_RES))

    best_dist = float("inf")
    best_idx = -1
    # Search the cell and its 8 neighbors
    for dlat in (-1, 0, 1):
        for dlon in (-1, 0, 1):
            bucket = _grid.get((cell_lat + dlat, cell_lon + dlon))
            if bucket is None:
                continue
            for clat, clon, idx in bucket:
                d = _haversine_km(lat, lon, clat, clon)
                if d < best_dist:
                    best_dist = d
                    best_idx = idx

    if best_idx < 0:
        return None
    return _cities[best_idx]


def lookup(
    lat: float,
    lon: float,
    cache_dir: Path,
) -> GeoResult | None:
    """Reverse geocode a single coordinate pair.

    Returns the nearest city or ``None`` if data is unavailable.
    """
    try:
        _load(cache_dir)
    except Exception:
        logger.warning("Geocoder data unavailable, skipping lookup", exc_info=True)
        return None
    return _nearest(lat, lon)


def batch_lookup(
    coords: list[tuple[float, float]],
    cache_dir: Path,
) -> list[GeoResult | None]:
    """Reverse geocode a batch of (lat, lon) pairs.

    Returns a list of the same length as *coords*, with ``None`` for
    any coordinate that could not be resolved.
    """
    if not coords:
        return []
    try:
        _load(cache_dir)
    except Exception:
        logger.warning("Geocoder data unavailable, skipping batch lookup", exc_info=True)
        return [None] * len(coords)
    return [_nearest(lat, lon) for lat, lon in coords]


def format_location(result: GeoResult | None, locale_map: dict[str, str] | None = None) -> str:
    """Format a GeoResult into a human-readable location string.

    *locale_map* is an optional ``{country_code:admin1_code → local_name}``
    mapping for non-English display names.
    """
    if result is None:
        return ""

    # Try locale map first for localized names
    if locale_map:
        key = f"{result.country_code}:{result.admin1}"
        local = locale_map.get(key)
        if local:
            return f"{result.name}, {local}"

    # Fallback to English name + country code
    parts = [result.name]
    if result.admin1:
        parts.append(result.admin1)
    parts.append(result.country_code)
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Cache management
# ---------------------------------------------------------------------------

def is_data_available(cache_dir: Path) -> bool:
    """Check whether the GeoNames CSV has been downloaded."""
    return (cache_dir / _CSV_FILENAME).exists()


def reset() -> None:
    """Reset the in-memory index (for testing)."""
    global _grid, _cities  # noqa: PLW0603
    _grid = None
    _cities = None
