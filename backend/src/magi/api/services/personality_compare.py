"""Personality configuration comparison helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

from ..routers.personality_config_schemas import PersonalityDiff


def flatten_dict(value: Any, prefix: str = "") -> Dict[str, Any]:
    flat: Dict[str, Any] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            next_prefix = f"{prefix}.{key}" if prefix else key
            flat.update(flatten_dict(child, next_prefix))
    else:
        flat[prefix] = value
    return flat


def build_personality_diffs(
    from_data: Dict[str, Any],
    to_data: Dict[str, Any],
    field_labels: Mapping[str, str],
) -> List[PersonalityDiff]:
    from_flat = flatten_dict(from_data)
    to_flat = flatten_dict(to_data)
    keys = sorted(set(from_flat) | set(to_flat))
    diffs: List[PersonalityDiff] = []
    for key in keys:
        if from_flat.get(key) != to_flat.get(key):
            diffs.append(
                PersonalityDiff(
                    field=key,
                    field_label=field_labels.get(key, key),
                    old_value=from_flat.get(key),
                    new_value=to_flat.get(key),
                )
            )
    return diffs


__all__ = ["build_personality_diffs", "flatten_dict"]