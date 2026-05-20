"""GET /api/memory/portrait/self — global self-portrait without LLM rendering."""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any

from fastapi import APIRouter, Query

from ....memory.portrait.contracts import PortraitObservation, PortraitPayload
from ....memory.provider import get_unified_memory
from ....user_profile.projection_repository import UserProfileProjectionRepository


logger = logging.getLogger(__name__)


_profile_repo_override: Any = None
_l2_override: Any = None


@contextmanager
def override_dependencies_for_test(*, profile_repo: Any = None, l2: Any = None):
    global _profile_repo_override, _l2_override
    _profile_repo_override = profile_repo
    _l2_override = l2
    try:
        yield
    finally:
        _profile_repo_override = None
        _l2_override = None


def _resolve_profile_repo() -> Any:
    if _profile_repo_override is not None:
        return _profile_repo_override
    try:
        unified = get_unified_memory()
    except Exception:
        return None
    db_path = str(getattr(getattr(unified, "l2", None), "db_path", "") or "")
    if not db_path:
        return None
    return UserProfileProjectionRepository(db_path)


def _resolve_l2() -> Any:
    if _l2_override is not None:
        return _l2_override
    try:
        unified = get_unified_memory()
    except Exception:
        return None
    return getattr(unified, "l2", None) if unified else None


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/portrait/self")
    async def get_self_portrait(
        user_id: str = Query(..., min_length=1),
    ) -> dict[str, Any]:
        profile_repo = _resolve_profile_repo()
        l2 = _resolve_l2()
        observations: list[PortraitObservation] = []

        projection = None
        if profile_repo is not None:
            try:
                projection = await profile_repo.get(user_id)
            except Exception as exc:
                logger.debug("self portrait: profile lookup failed: %s", exc)
        observations.extend(_observations_from_projection(projection))

        snapshot = None
        if l2 is not None:
            try:
                snapshots = await l2.list_tom_snapshots(
                    entity_id=f"user:{user_id}", limit=1
                )
                snapshot = snapshots[0] if snapshots else None
            except Exception as exc:
                logger.debug("self portrait: tom snapshot lookup failed: %s", exc)
        observations.extend(_observations_from_snapshot(snapshot))

        if l2 is not None:
            try:
                assertion_items = await l2.list_tom_assertions(
                    entity_id=f"user:{user_id}", limit=50, offset=0,
                )
            except Exception as exc:
                logger.debug("self portrait: assertion lookup failed: %s", exc)
                assertion_items = []
            if assertion_items:
                observations.extend(_observations_from_assertion_items(assertion_items))

        is_cold_start = len(observations) == 0
        payload = PortraitPayload(
            session_id="",
            persona_id="",
            topic="self",
            generated_at=int(time.time()),
            observations=observations,
            is_cold_start=is_cold_start,
            cold_start_line=None,
            cold_start_reason=("no_observations" if is_cold_start else None),
        )
        return payload.to_dict()

    return router


def _observations_from_projection(projection: Any) -> list[PortraitObservation]:
    if projection is None:
        return []

    facts: list[tuple[str, str]] = []
    if projection.real_name:
        facts.append((f"你叫 {projection.real_name}", "real_name"))
    if projection.preferred_form_of_address:
        facts.append((f"称呼你「{projection.preferred_form_of_address}」", "preferred_form_of_address"))
    if projection.home_location:
        facts.append((f"住在{projection.home_location}", "home_location"))
    for key, value in (projection.preferences or {}).items():
        facts.append((f"偏好：{key} = {value}", f"preference:{key}"))
    for key, value in (projection.communication or {}).items():
        facts.append((f"沟通风格：{key} = {value}", f"communication:{key}"))
    for key, value in (projection.state or {}).items():
        facts.append((f"近期状态：{key} = {value}", f"state:{key}"))

    return [
        PortraitObservation(
            kind="assertion",
            text=text,
            basis_count=1,
            basis_summary="user_profile_projection",
            basis_refs=[ref],
        )
        for text, ref in facts
    ]


def _observations_from_snapshot(snapshot: dict[str, Any] | None) -> list[PortraitObservation]:
    if not snapshot:
        return []
    core_traits = snapshot.get("core_traits")
    # core_traits may be a dict (JSON-decoded) or a plain string
    if isinstance(core_traits, dict):
        text = "; ".join(f"{k}: {v}" for k, v in core_traits.items()).strip()
    else:
        text = str(core_traits or "").strip()
    if not text:
        return []
    return [PortraitObservation(
        kind="reflection",
        text=text,
        basis_count=int(snapshot.get("evidence_count") or 1),
        basis_summary="L2 ToM snapshot",
        basis_refs=[str(snapshot.get("snapshot_id") or "tom-latest")],
    )]


def _observations_from_assertion_items(items: list[dict[str, Any]]) -> list[PortraitObservation]:
    if not items:
        return []
    obs: list[PortraitObservation] = []
    for item in items[:20]:
        trait = str(item.get("trait_name") or item.get("predicate") or "")
        value = str(item.get("value") or item.get("trait_value") or "")
        if not trait or not value:
            continue
        obs.append(PortraitObservation(
            kind="assertion",
            text=f"{trait}: {value}",
            basis_count=int(item.get("evidence_count") or 1),
            basis_summary="L2 assertion",
            basis_refs=[str(item.get("assertion_id") or "")],
        ))
    return obs
