"""Personality presets list API."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from ..avatar_paths import resolve_avatar_public_url, user_avatar_dir
from ...utils.packaged_paths import get_backend_root


personality_presets_router = APIRouter()


class PersonalityPresetItem(BaseModel):
    id: str
    name: str
    occupation: str = ""
    description: str = ""
    avatar: str = ""
    prompt: str = ""
    group: str = "general"
    order: int = 999


class PersonalitiesResponse(BaseModel):
    success: bool = True
    message: str = "OK"
    data: List[PersonalityPresetItem] = Field(default_factory=list)


class PersonalityPresetDetailResponse(BaseModel):
    success: bool = True
    message: str = "OK"
    data: Optional[Dict[str, Any]] = None


def _resolve_language_dir(lang: Optional[str]) -> Path:
    root = get_backend_root() / "personalities"
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
        meta = data.get("meta", {})
        basic = data.get("persona_entity", {}).get("basic_profile", {})
        identity = data.get("persona_entity", {}).get("core_identity", {})
        narrative = identity.get("inner_narrative", "") or basic.get("core_background", "")
        description = basic.get("description") or basic.get("occupation") or (narrative[:200] if narrative else "")
        return PersonalityPresetItem(
            id=file_path.stem,
            name=basic.get("name", file_path.stem),
            occupation=basic.get("occupation", ""),
            description=description,
            avatar=basic.get("avatar", ""),
            prompt=narrative,
            group=meta.get("group", "general"),
            order=meta.get("order", 999),
        )
    except Exception:
        return PersonalityPresetItem(
            id=file_path.stem,
            name=file_path.stem,
        )

@personality_presets_router.get(
    "/",
    response_model=PersonalitiesResponse,
    summary="List personality presets",
    description="Return preset personalities under the selected language directory, sorted by preset order.",
)
async def list_personality_presets(lang: Optional[str] = Query(default="zh")):
    lang_dir = _resolve_language_dir(lang)
    presets: List[PersonalityPresetItem] = []
    for file_path in lang_dir.glob("*.json"):
        preset = _parse_json_preset(file_path)
        preset.avatar = resolve_avatar_public_url(preset.avatar)
        presets.append(preset)
    # Sort by order field
    presets.sort(key=lambda p: p.order)
    return PersonalitiesResponse(data=presets)


@personality_presets_router.get(
    "/{preset_id}",
    response_model=PersonalityPresetDetailResponse,
    summary="Get personality preset detail",
    description="Return full JSON configuration for a specific built-in preset.",
)
async def get_personality_preset(
    preset_id: str,
    lang: Optional[str] = Query(default="zh"),
):
    """Get full configuration for a specific personality preset."""
    lang_dir = _resolve_language_dir(lang)
    file_path = lang_dir / f"{preset_id}.json"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Personality preset '{preset_id}' not found")
    try:
        content = file_path.read_text(encoding="utf-8")
        data = json.loads(content)
        basic_profile = data.get("persona_entity", {}).get("basic_profile", {})
        basic_profile["avatar"] = resolve_avatar_public_url(basic_profile.get("avatar", ""))
        return PersonalityPresetDetailResponse(data=data)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail=f"Failed to parse personality preset '{preset_id}'")


@personality_presets_router.post(
    "/avatar/upload",
    summary="Upload custom avatar",
    description="Upload a custom avatar image into the user personality avatar directory.",
)
async def upload_personality_avatar(file: UploadFile = File(...)):
    allowed_suffixes = {".jpg", ".jpeg", ".png", ".webp"}
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in allowed_suffixes:
        raise HTTPException(status_code=400, detail="Unsupported image format")
    if file.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=400, detail="Unsupported image content type")

    avatar_dir = user_avatar_dir()
    avatar_dir.mkdir(parents=True, exist_ok=True)

    safe_stem = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in Path(file.filename or "").stem).strip("_")
    if not safe_stem:
        safe_stem = "avatar"
    filename = f"{safe_stem}_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}{suffix}"
    target = avatar_dir / filename

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file is not allowed")
    target.write_bytes(content)

    return {"filename": filename, "url": resolve_avatar_public_url(filename)}
