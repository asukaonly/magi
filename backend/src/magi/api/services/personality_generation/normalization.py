"""Generated payload normalization and merge helpers."""

from __future__ import annotations

from typing import Any, Dict, Sequence

from .constants import (
    GENERATION_INTERNAL_KEYS,
    META_DESIGN_FIELDS,
    META_DESIGN_KEY,
)
from .normalization_primitives import (
    _clean_generated_text_tree,
    _is_ambiguous_language_target,
    _is_chinese_target,
    _payload_looks_chinese,
    _string_dict,
    _string_list,
)
from .registers import _complete_registers
from .schema_completion import (
    _complete_bootstrap,
    _complete_dynamic_state_rules,
    _complete_examples,
    _complete_persona_layers,
    _complete_quiet_hours,
    _complete_signature_triggers,
)


def _pick_keys(
    payload: dict[str, Any],
    keys: Sequence[str],
) -> dict[str, Any]:
    return {key: payload[key] for key in keys if key in payload}


def _deep_merge_payload(
    base: dict[str, Any],
    update: dict[str, Any],
) -> dict[str, Any]:
    """Merge nested personality fragments without deleting existing sections."""
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge_payload(base[key], value)
        else:
            base[key] = value
    return base


def _generation_meta_design(spine: dict[str, Any]) -> dict[str, str]:
    raw_meta = spine.get(META_DESIGN_KEY) if isinstance(spine, dict) else None
    meta = raw_meta if isinstance(raw_meta, dict) else {}
    return {
        "core_theme": str(
            meta.get("core_theme") or "[not specified - infer from the persona spine]"
        ),
        "failure_mode": str(
            meta.get("failure_mode")
            or "[not specified - apply general anti-AI-performance principles]"
        ),
        "key_constraint": str(
            meta.get("key_constraint")
            or "[not specified - keep ordinary presence stronger than style markers]"
        ),
    }


def _complete_generation_meta_design(payload: dict[str, Any]) -> None:
    raw_meta = payload.get(META_DESIGN_KEY)
    meta = raw_meta if isinstance(raw_meta, dict) else {}
    payload[META_DESIGN_KEY] = {field: str(meta.get(field) or "") for field in META_DESIGN_FIELDS}


def _runtime_payload_from_combined(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Drop generation-only design anchors before runtime schema validation."""
    return {key: value for key, value in payload.items() if key not in GENERATION_INTERNAL_KEYS}


def _should_use_chinese_copy(
    payload: Dict[str, Any],
    target_language: str,
) -> bool:
    """Decide whether normalizer fallback copy should be written in Chinese."""
    return _is_chinese_target(target_language) or (
        _is_ambiguous_language_target(target_language) and _payload_looks_chinese(payload)
    )


def normalize_generated_personality_payload(
    payload: Dict[str, Any],
    target_language: str = "English",
) -> Dict[str, Any]:
    """Normalize common scalar mismatches and complete required runtime fields."""
    payload = _clean_generated_text_tree(payload)
    for field in ("name", "avatar", "description", "appearance_prompt"):
        value = payload.get(field)
        if value is None:
            continue
        if not isinstance(value, str):
            payload[field] = str(value)

    identity_core = payload.setdefault("identity_core", {})
    if not isinstance(identity_core, dict):
        identity_core = {}
        payload["identity_core"] = identity_core
    value = identity_core.get("identity_statement")
    if value is not None and not isinstance(value, str):
        identity_core["identity_statement"] = str(value)
    for key in ("values_loved", "values_rejected", "attention_biases"):
        identity_core[key] = _string_list(identity_core.get(key))

    idiolect = payload.setdefault("idiolect", {})
    if not isinstance(idiolect, dict):
        idiolect = {}
        payload["idiolect"] = idiolect
    sentence_style = idiolect.get("sentence_style")
    if sentence_style is not None and not isinstance(sentence_style, str):
        idiolect["sentence_style"] = str(sentence_style)
    for key in ("vocab_available", "vocab_avoided", "structural_quirks"):
        idiolect[key] = _string_list(idiolect.get(key))
    raw_chattiness = idiolect.get("chattiness")
    if raw_chattiness is None:
        idiolect["chattiness"] = 0.5
    else:
        try:
            idiolect["chattiness"] = max(
                0.0,
                min(1.0, float(raw_chattiness)),
            )
        except (TypeError, ValueError):
            idiolect["chattiness"] = 0.5

    use_chinese = _should_use_chinese_copy(payload, target_language)
    _complete_registers(payload, use_chinese)
    _complete_quiet_hours(payload, use_chinese)
    _complete_signature_triggers(payload, use_chinese)
    _complete_persona_layers(payload)
    _complete_bootstrap(payload, use_chinese)
    _complete_examples(payload, use_chinese)
    _complete_dynamic_state_rules(payload, use_chinese)

    payload["milestone_conditions"] = _string_dict(payload.get("milestone_conditions"))
    raw_interim_lines = payload.get("interim_lines")
    interim_lines: dict[str, Any] = raw_interim_lines if isinstance(raw_interim_lines, dict) else {}
    payload["interim_lines"] = {
        str(key): _string_list(value) for key, value in interim_lines.items()
    }
    return payload
