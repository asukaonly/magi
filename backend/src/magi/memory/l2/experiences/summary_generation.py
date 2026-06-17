"""Generate missing L3 reviews for L2 experiences."""

from __future__ import annotations

from typing import Any


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
            if callable(get_review) and await get_review(experience_id):
                continue
            experience = await get_experience(experience_id=experience_id)
            if not experience:
                continue
            members = await list_members(experience_id=experience_id)
            result = await generate_review(
                l1_store=l1_store,
                l2_store=l2_store,
                experience=experience,
                experience_members=members,
            )
            if result is not None:
                generated += 1
        except Exception as exc:  # noqa: BLE001 - batch generation should keep going.
            errors.append(f"{experience_id}: {exc}")
    return {"generated": generated, "errors": errors}


__all__ = ["generate_missing_experience_summaries"]
