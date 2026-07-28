"""Primitive input and value normalization helpers."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from ...routers.personality_config_schemas import PersonalityConfigModel


CJK_TEXT_RE = re.compile(r"[\u3400-\u9fff]")
CJK_INTERNAL_SPACE_RE = re.compile(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])")
CJK_BEFORE_PUNCTUATION_RE = re.compile(r"(?<=[\u3400-\u9fff])\s+(?=[，。！？、；：])")
AMBIGUOUS_LANGUAGE_VALUES = {"", "auto", "automatic", "自动"}


def _is_chinese_target(target_language: str) -> bool:
    return target_language.strip().lower() in {
        "chinese",
        "zh",
        "zh-cn",
        "中文",
        "简体中文",
    }


def _is_ambiguous_language_target(target_language: str) -> bool:
    return target_language.strip().lower() in AMBIGUOUS_LANGUAGE_VALUES


def _payload_looks_chinese(payload: Dict[str, Any]) -> bool:
    sample = " ".join(str(payload.get(key) or "") for key in ("name", "description"))
    raw_identity_core = payload.get("identity_core")
    identity_core: dict[str, Any] = raw_identity_core if isinstance(raw_identity_core, dict) else {}
    sample = f"{sample} {identity_core.get('identity_statement') or ''}"
    return bool(CJK_TEXT_RE.search(sample))


def _resolve_generation_target_language(
    description: str,
    target_language: str,
    current_config: Optional[PersonalityConfigModel],
) -> str:
    requested_language = (target_language or "English").strip()
    if requested_language and not _is_ambiguous_language_target(requested_language):
        return requested_language
    if CJK_TEXT_RE.search(description):
        return "Chinese"
    if current_config is not None and _payload_looks_chinese(current_config.model_dump()):
        return "Chinese"
    return "English"


def _clean_generated_text(value: str) -> str:
    text = CJK_INTERNAL_SPACE_RE.sub("", value)
    text = CJK_BEFORE_PUNCTUATION_RE.sub("", text)
    return text.strip()


def _clean_generated_text_tree(value: Any) -> Any:
    if isinstance(value, str):
        return _clean_generated_text(value)
    if isinstance(value, list):
        return [_clean_generated_text_tree(item) for item in value]
    if isinstance(value, dict):
        return {key: _clean_generated_text_tree(item) for key, item in value.items()}
    return value


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [line.strip() for line in value.split("\n") if line.strip()]
    return [str(value).strip()] if str(value).strip() else []


def _string_field(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    if isinstance(value, str):
        return value.strip() or fallback
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        return "\n".join(items) or fallback
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).strip() or fallback


def _string_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for key, item in value.items():
        normalized_key = str(key).strip()
        if normalized_key:
            result[normalized_key] = str(item).strip()
    return result


def _ensure_dict(payload: Dict[str, Any], key: str) -> Dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        value = {}
        payload[key] = value
    return value


def _ensure_list(payload: Dict[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    if not isinstance(value, list):
        value = []
        payload[key] = value
    return value
