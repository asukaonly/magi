"""Shared image upload helpers for memory-facing routes."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, UploadFile, status

from ....memory.manual_entries.asset_store import (
    ACCEPTED_CONTENT_TYPES,
    KNOWN_UNSUPPORTED_CONTENT_TYPES,
    MAX_UPLOAD_BYTES,
)


async def store_uploaded_image_asset(file: UploadFile, asset_store: Any) -> dict[str, Any]:
    """Validate and store one uploaded image using the memory asset store."""
    content_type = (file.content_type or "").lower()
    if content_type in KNOWN_UNSUPPORTED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=KNOWN_UNSUPPORTED_CONTENT_TYPES[content_type],
        )
    if content_type not in ACCEPTED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"图片格式不支持: {content_type or 'unknown'}",
        )

    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"图片超过 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB 上限",
        )
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty upload",
        )

    asset_ref = asset_store.store_bytes(data, content_type=content_type)
    return {
        "asset_ref": asset_ref,
        "content_type": content_type,
        "byte_size": len(data),
    }
