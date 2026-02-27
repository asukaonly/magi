"""Personality presets list API."""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field


personalities_router = APIRouter()


class PersonalityPresetItem(BaseModel):
    id: str
    name: str
    occupation: str = ""
    description: str = ""
    prompt: str = ""


class PersonalitiesResponse(BaseModel):
    success: bool = True
    message: str = "OK"
    data: List[PersonalityPresetItem] = Field(default_factory=list)


def _resolve_language_dir(lang: Optional[str]) -> Path:
    root = Path(__file__).resolve().parents[4] / "personalities"
    if not root.exists():
        root.mkdir(parents=True, exist_ok=True)
    normalized = (lang or "zh").lower()
    if normalized.startswith("zh"):
        candidate = root / "zh"
    elif normalized.startswith("en"):
        candidate = root / "en"
    else:
        candidate = root / normalized
    if candidate.exists():
        return candidate
    fallback = root / "zh"
    if fallback.exists():
        return fallback
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def _parse_json_preset(file_path: Path) -> PersonalityPresetItem:
    """Parse personality preset from JSON file."""
    try:
        content = file_path.read_text(encoding="utf-8")
        data = json.loads(content)
        basic = data.get("persona_entity", {}).get("basic_profile", {})
        core_background = basic.get("core_background", "")
        return PersonalityPresetItem(
            id=file_path.stem,
            name=basic.get("name", file_path.stem),
            occupation=basic.get("occupation", ""),
            description=core_background[:200] if core_background else "",
            prompt=core_background,
        )
    except Exception:
        return PersonalityPresetItem(
            id=file_path.stem,
            name=file_path.stem,
        )


@personalities_router.get("/", response_model=PersonalitiesResponse)
async def list_personality_presets(lang: Optional[str] = Query(default="zh")):
    lang_dir = _resolve_language_dir(lang)
    presets: List[PersonalityPresetItem] = []
    for file_path in sorted(lang_dir.glob("*.json")):
        presets.append(_parse_json_preset(file_path))
    return PersonalitiesResponse(data=presets)
