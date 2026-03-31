"""Tests for photo library normalizer helpers — entity extraction and display formatting."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# photo-library has a hyphen, so we must load via importlib
_plugin_dir = Path(__file__).resolve().parents[3] / "plugins" / "photo-library"

def _load_module(name: str):
    path = _plugin_dir / f"{name}.py"
    spec = importlib.util.spec_from_file_location(
        f"photo_library_{name}", path,
        submodule_search_locations=[str(_plugin_dir)],
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod

_norm_mod = _load_module("normalizers")
build_entity_hints = _norm_mod.build_entity_hints
build_relation_candidates = _norm_mod.build_relation_candidates
camera_display_name = _norm_mod.camera_display_name
image_dimensions_label = _norm_mod.image_dimensions_label
shooting_params_summary = _norm_mod.shooting_params_summary


# ---------------------------------------------------------------------------
# camera_display_name
# ---------------------------------------------------------------------------

class TestCameraDisplayName:
    def test_make_and_model(self):
        assert camera_display_name("Canon", "EOS R5") == "Canon EOS R5"

    def test_model_includes_make(self):
        # "Apple iPhone 15 Pro" already starts with "Apple"
        assert camera_display_name("Apple", "Apple iPhone 15 Pro") == "Apple iPhone 15 Pro"

    def test_only_model(self):
        assert camera_display_name("", "iPhone 15 Pro") == "iPhone 15 Pro"

    def test_only_make(self):
        assert camera_display_name("Sony", "") == "Sony"

    def test_both_empty(self):
        assert camera_display_name("", "") == ""

    def test_case_insensitive_dedup(self):
        assert camera_display_name("SONY", "Sony A7R V") == "Sony A7R V"

    def test_whitespace_stripping(self):
        assert camera_display_name("  Canon  ", "  EOS R5  ") == "Canon EOS R5"


# ---------------------------------------------------------------------------
# shooting_params_summary
# ---------------------------------------------------------------------------

class TestShootingParamsSummary:
    def test_full_params(self):
        item = {
            "focal_length": "50.0mm",
            "aperture": "f/1.8",
            "exposure_time": "1/250s",
            "iso": "400",
        }
        result = shooting_params_summary(item)
        assert "50.0mm" in result
        assert "f/1.8" in result
        assert "1/250s" in result
        assert "ISO400" in result

    def test_partial_params(self):
        item = {"focal_length": "24.0mm", "iso": "100"}
        result = shooting_params_summary(item)
        assert "24.0mm" in result
        assert "ISO100" in result

    def test_empty_params(self):
        assert shooting_params_summary({}) == ""

    def test_missing_keys(self):
        assert shooting_params_summary({"camera_make": "Canon"}) == ""


# ---------------------------------------------------------------------------
# image_dimensions_label
# ---------------------------------------------------------------------------

class TestImageDimensionsLabel:
    def test_valid_dimensions(self):
        assert image_dimensions_label(4032, 3024) == "4032x3024"

    def test_zero_width(self):
        assert image_dimensions_label(0, 3024) == ""

    def test_both_zero(self):
        assert image_dimensions_label(0, 0) == ""


# ---------------------------------------------------------------------------
# build_entity_hints
# ---------------------------------------------------------------------------

class TestBuildEntityHints:
    def test_camera_entity(self):
        item = {"camera_make": "Canon", "camera_model": "EOS R5"}
        hints = build_entity_hints(item)
        assert len(hints) >= 1
        camera_hints = [h for h in hints if h["entity_type"] == "device"]
        assert len(camera_hints) == 1
        assert camera_hints[0]["canonical_name_hint"] == "Canon EOS R5"

    def test_gps_entity(self):
        item = {
            "camera_make": "",
            "camera_model": "",
            "latitude": 35.6586,
            "longitude": 139.7454,
        }
        hints = build_entity_hints(item)
        location_hints = [h for h in hints if h["entity_type"] == "location"]
        assert len(location_hints) == 1
        assert "35.6586" in location_hints[0]["mention_text"]
        assert location_hints[0]["attributes"]["latitude"] == 35.6586

    def test_both_camera_and_gps(self):
        item = {
            "camera_make": "Apple",
            "camera_model": "iPhone 15 Pro",
            "latitude": 35.6586,
            "longitude": 139.7454,
        }
        hints = build_entity_hints(item)
        types = {h["entity_type"] for h in hints}
        assert "device" in types
        assert "location" in types

    def test_no_metadata(self):
        hints = build_entity_hints({"camera_make": "", "camera_model": ""})
        assert len(hints) == 0


# ---------------------------------------------------------------------------
# build_relation_candidates
# ---------------------------------------------------------------------------

class TestBuildRelationCandidates:
    def _base_item(self) -> dict:
        return {
            "asset_local_id": "abc123",
            "path": "/photos/sunset.jpg",
            "filename": "sunset.jpg",
            "modified_at": 1710000000.0,
            "capture_timestamp": 1710000000.0,
            "camera_make": "",
            "camera_model": "",
        }

    def test_always_has_captured(self):
        item = self._base_item()
        candidates = build_relation_candidates(item)
        captured = [c for c in candidates if c["predicate"] == "CAPTURED"]
        assert len(captured) == 1
        assert captured[0]["subject_id"] == "user:self"

    def test_gps_adds_related_to(self):
        item = self._base_item()
        item["latitude"] = 35.6586
        item["longitude"] = 139.7454
        candidates = build_relation_candidates(item)
        related = [c for c in candidates if c["predicate"] == "RELATED_TO"]
        assert len(related) == 1
        assert "location:" in related[0]["object_id"]

    def test_camera_adds_created(self):
        item = self._base_item()
        item["camera_make"] = "Canon"
        item["camera_model"] = "EOS R5"
        candidates = build_relation_candidates(item)
        created = [c for c in candidates if c["predicate"] == "CREATED"]
        assert len(created) == 1
        assert "device:" in created[0]["subject_id"]

    def test_full_metadata_three_relations(self):
        item = self._base_item()
        item["camera_make"] = "Canon"
        item["camera_model"] = "EOS R5"
        item["latitude"] = 35.0
        item["longitude"] = 139.0
        candidates = build_relation_candidates(item)
        predicates = {c["predicate"] for c in candidates}
        assert predicates == {"CAPTURED", "RELATED_TO", "CREATED"}

    def test_minimal_item_one_relation(self):
        item = self._base_item()
        candidates = build_relation_candidates(item)
        assert len(candidates) == 1
        assert candidates[0]["predicate"] == "CAPTURED"
