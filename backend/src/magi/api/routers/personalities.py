"""Personality presets list API."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field


personalities_router = APIRouter()


class PersonalityPresetItem(BaseModel):
    id: str
    name: str
    description: str
    prompt: str


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


def _parse_markdown_preset(file_path: Path) -> PersonalityPresetItem:
    content = file_path.read_text(encoding="utf-8").strip()
    lines = content.splitlines()
    header = lines[0].lstrip("#").strip() if lines else file_path.stem
    description = ""
    prompt_start = 0
    for idx, line in enumerate(lines[1:], start=1):
        if line.strip():
            description = line.strip()
            prompt_start = idx + 1
            break
    prompt = "\n".join(lines[prompt_start:]).strip() or content
    return PersonalityPresetItem(
        id=file_path.stem,
        name=header or file_path.stem,
        description=description or f"Preset personality: {file_path.stem}",
        prompt=prompt,
    )


@personalities_router.get("/", response_model=PersonalitiesResponse)
async def list_personality_presets(lang: Optional[str] = Query(default="zh")):
    lang_dir = _resolve_language_dir(lang)
    presets: List[PersonalityPresetItem] = []
    for file_path in sorted(lang_dir.glob("*.md")):
        presets.append(_parse_markdown_preset(file_path))
    return PersonalitiesResponse(data=presets)
