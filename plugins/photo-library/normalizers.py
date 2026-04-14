"""Normalization helpers for photo library timeline ingestion."""
from __future__ import annotations

from typing import Any


def camera_display_name(make: str, model: str) -> str:
    """Build a human-readable camera name, deduplicating make from model."""
    make = make.strip()
    model = model.strip()
    if not make and not model:
        return ""
    if not make:
        return model
    if not model:
        return make
    # Many models already include the make name, e.g. "Apple iPhone 15 Pro"
    if model.lower().startswith(make.lower()):
        return model
    return f"{make} {model}"


def shooting_params_summary(item: dict[str, Any]) -> str:
    """Build a compact shooting parameters string like '50mm f/1.8 1/250s ISO400'."""
    parts: list[str] = []
    if item.get("focal_length"):
        parts.append(str(item["focal_length"]))
    if item.get("aperture"):
        parts.append(str(item["aperture"]))
    if item.get("exposure_time"):
        parts.append(str(item["exposure_time"]))
    if item.get("iso"):
        parts.append(f"ISO{item['iso']}")
    return " ".join(parts)


def image_dimensions_label(width: int, height: int) -> str:
    """Return a dimensions label like '4032x3024'."""
    if width > 0 and height > 0:
        return f"{width}x{height}"
    return ""


def build_entity_hints(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract entity hints from photo metadata for L2 cognition."""
    hints: list[dict[str, Any]] = []

    # Camera as entity
    camera = camera_display_name(
        str(item.get("camera_make", "")),
        str(item.get("camera_model", "")),
    )
    if camera:
        hints.append({
            "mention_text": camera,
            "entity_type": "device",
            "canonical_name_hint": camera,
        })

    # GPS location as entity — prefer reverse-geocoded name
    lat = item.get("latitude")
    lon = item.get("longitude")
    location_name = str(item.get("location_name") or "")
    if lat is not None and lon is not None:
        coord_label = f"{lat:.4f}, {lon:.4f}"
        canonical = location_name or coord_label
        hints.append({
            "mention_text": canonical,
            "entity_type": "location",
            "canonical_name_hint": canonical,
            "attributes": {"latitude": lat, "longitude": lon},
        })

    return hints


def build_relation_candidates(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Generate conservative relation candidates for a photo item."""
    candidates: list[dict[str, Any]] = []
    capture_ts = float(item.get("capture_timestamp") or item.get("modified_at") or 0.0)
    path = str(item.get("path", ""))
    image_type = str(item.get("image_type", "photo"))
    source_kind = "screenshot" if image_type == "screenshot" else "photo"

    # CAPTURED: user captured this photo / took this screenshot
    candidates.append({
        "subject_id": "user:self",
        "subject_type": "user",
        "predicate": "CAPTURED",
        "object_id": f"photo:{item.get('asset_local_id', '')}",
        "object_type": image_type,
        "confidence": 0.85,
        "observed_at": capture_ts,
        "object_attributes": {
            "path": path,
            "filename": str(item.get("filename", "")),
            "source_kind": source_kind,
        },
    })

    # RELATED_TO location if GPS available
    lat = item.get("latitude")
    lon = item.get("longitude")
    location_name = str(item.get("location_name") or "")
    if lat is not None and lon is not None:
        loc_id = location_name or f"{lat:.4f},{lon:.4f}"
        candidates.append({
            "subject_id": f"photo:{item.get('asset_local_id', '')}",
            "subject_type": "photo",
            "predicate": "RELATED_TO",
            "object_id": f"location:{loc_id}",
            "object_type": "location",
            "confidence": 0.9,
            "observed_at": capture_ts,
            "object_attributes": {
                "latitude": lat,
                "longitude": lon,
                "location_name": location_name,
                "source_kind": "gps",
            },
        })

    # CREATED: if camera info is available, link photo to device
    camera = camera_display_name(
        str(item.get("camera_make", "")),
        str(item.get("camera_model", "")),
    )
    if camera:
        candidates.append({
            "subject_id": f"device:{camera}",
            "subject_type": "device",
            "predicate": "CREATED",
            "object_id": f"photo:{item.get('asset_local_id', '')}",
            "object_type": "photo",
            "confidence": 0.8,
            "observed_at": capture_ts,
            "object_attributes": {
                "camera": camera,
                "source_kind": "exif",
            },
        })

    return candidates
