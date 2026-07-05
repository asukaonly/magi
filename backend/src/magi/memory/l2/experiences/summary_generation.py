"""Generate missing L3 reviews for L2 experiences."""

from __future__ import annotations

import json
import re
from typing import Any

from ...l3.episode_backwrite import backwrite_experience_review

_PLACEHOLDER_LABELS = {
    "untitled",
    "untitled episode",
    "untitled experience",
    "experience",
}
_GENERIC_REVIEW_CONTENTS = {
    "magi grouped related episode evidence into a narratable memory.",
}
_MACHINE_LABEL_PATTERN = re.compile(r"^(?:[0-9a-f]{10,}|[0-9A-HJKMNP-TV-Z]{12,})$", re.IGNORECASE)
_LOW_VALUE_LABELS = {
    "local_user",
    "local user",
    "self",
    "user",
    "user self",
}


def _decode_metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
        except (json.JSONDecodeError, TypeError, ValueError):
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _is_placeholder_label(value: Any) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return True
    if text in _PLACEHOLDER_LABELS or text.startswith("untitled exper"):
        return True
    parts = [
        part.strip()
        for part in text.replace("|", "/").split("/")
        if part.strip()
    ]
    return bool(parts) and all(
        part in _PLACEHOLDER_LABELS or part.startswith("untitled exper")
        for part in parts
    )


def _has_low_value_label_part(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    parts = [
        part.strip()
        for part in text.replace("|", "/").split("/")
        if part.strip()
    ]
    if not parts:
        return True
    for part in parts:
        raw_part = part.strip()
        normalized = raw_part.replace("_", " ").replace("-", " ").casefold()
        if (
            raw_part.isdigit()
            or _MACHINE_LABEL_PATTERN.fullmatch(raw_part)
            or normalized in _LOW_VALUE_LABELS
        ):
            return True
    return False


def _is_generic_review_content(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return not text or text in _GENERIC_REVIEW_CONTENTS


def _looks_like_raw_title_dump(value: Any) -> bool:
    text = str(value or "").strip().casefold()
    if not text:
        return False
    return (
        "chrome 浏览" in text
        or "google search" in text
        or (
            text.count("；") >= 2
            and any(token in text for token in ("chrome", "google", "github", "gmail"))
        )
    )


def _review_needs_refresh(summary: dict[str, Any]) -> bool:
    metadata = _decode_metadata(summary.get("insight_metadata"))
    label = metadata.get("label") or summary.get("label")
    return (
        bool(metadata.get("fallback"))
        or _is_placeholder_label(label)
        or _has_low_value_label_part(label)
        or _is_generic_review_content(summary.get("content"))
        or _looks_like_raw_title_dump(summary.get("content"))
    )


async def _get_experience_ids(l2_store: Any, experience_ids: list[str] | None, limit: int) -> list[str]:
    if experience_ids is not None:
        return [str(item).strip() for item in experience_ids if str(item).strip()]
    list_experiences = getattr(l2_store, "list_experiences", None)
    if not callable(list_experiences):
        return []
    experiences = await list_experiences(status="active", limit=limit)
    return [
        str(item.get("experience_id") or "").strip()
        for item in experiences
        if item.get("experience_id")
    ]


async def generate_missing_experience_summaries(
    *,
    l1_store: Any,
    l2_store: Any,
    l3_store: Any,
    experience_ids: list[str] | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Generate L3 review summaries for active experiences lacking one."""
    if l1_store is None or l2_store is None or l3_store is None:
        return {"generated": 0, "errors": []}
    generate_review = getattr(l3_store, "generate_experience_summary", None)
    get_review = getattr(l3_store, "get_episodic_summary_by_experience_id", None)
    get_experience = getattr(l2_store, "get_experience", None)
    list_members = getattr(l2_store, "list_experience_members", None)
    if not callable(generate_review) or not callable(get_experience) or not callable(list_members):
        return {"generated": 0, "errors": []}

    generated = 0
    errors: list[str] = []
    for experience_id in await _get_experience_ids(l2_store, experience_ids, limit):
        try:
            existing_review = await get_review(experience_id) if callable(get_review) else None
            experience = await get_experience(experience_id=experience_id)
            if not experience:
                continue
            if existing_review is not None and not _review_needs_refresh(existing_review):
                await backwrite_experience_review(
                    l2_store,
                    experience=experience,
                    summary=existing_review,
                )
                continue
            members = await list_members(experience_id=experience_id)
            result = await generate_review(
                l1_store=l1_store,
                l2_store=l2_store,
                experience=experience,
                experience_members=members,
            )
            if result is not None:
                await backwrite_experience_review(
                    l2_store,
                    experience=experience,
                    summary=result,
                )
                generated += 1
        except Exception as exc:  # noqa: BLE001 - batch generation should keep going.
            errors.append(f"{experience_id}: {exc}")
    return {"generated": generated, "errors": errors}


__all__ = ["generate_missing_experience_summaries"]
