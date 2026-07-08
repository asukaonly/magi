"""GET /api/memory/portrait/self — global self-portrait without LLM rendering."""

from __future__ import annotations

import logging
import re
import time
from contextlib import contextmanager
from typing import Any

from fastapi import APIRouter, Query

from ....memory.provider import get_unified_memory
from ....user_profile.portrait_contracts import UserPortraitObservation, UserPortraitPayload
from ....user_profile.portrait_graph_signals import (
    PortraitGraphSignal,
    collect_portrait_graph_signals,
)
from ....user_profile.portrait_projection_builder import UserPortraitProjectionBuilder
from ....user_profile.portrait_projection_freshness import portrait_projection_is_stale
from ....user_profile.portrait_signal_policy import (
    PORTRAIT_WORLD_GROUP_IDS,
    PORTRAIT_RECENT_FAMILIES,
    PORTRAIT_REVIEW_STATES,
    PORTRAIT_SOURCE_STRENGTH,
    PORTRAIT_VALIDATION_STRENGTH,
    classify_assertion_portrait,
)
from ....user_profile.portrait_values import snapshot_recent_values
from ....user_profile.portrait_projection_repository import UserPortraitProjectionRepository
from ....user_profile.projection_repository import UserProfileProjectionRepository

logger = logging.getLogger(__name__)


_ASSERTION_REF_MIN_LENGTH = 20
_WORLD_GROUP_IDS = PORTRAIT_WORLD_GROUP_IDS
_INTERNAL_SOURCE_KEYS = {
    "external_activity",
    "photo_library",
    "photo_library_apple_photos",
    "photo_library_directory",
}


_profile_repo_override: Any = None
_portrait_repo_override: Any = None
_l2_override: Any = None


@contextmanager
def override_dependencies_for_test(
    *, profile_repo: Any = None, portrait_repo: Any = None, l2: Any = None
):
    global _profile_repo_override, _portrait_repo_override, _l2_override
    _profile_repo_override = profile_repo
    _portrait_repo_override = portrait_repo
    _l2_override = l2
    try:
        yield
    finally:
        _profile_repo_override = None
        _portrait_repo_override = None
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


def _resolve_portrait_repo() -> Any:
    if _portrait_repo_override is not None:
        return _portrait_repo_override
    try:
        unified = get_unified_memory()
    except Exception:
        return None
    db_path = str(getattr(getattr(unified, "l2", None), "db_path", "") or "")
    if not db_path:
        return None
    return UserPortraitProjectionRepository(db_path)


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
        return await _get_self_portrait(user_id)

    return router


async def _get_self_portrait(user_id: str) -> dict[str, Any]:
    portrait_repo = _resolve_portrait_repo()
    l2 = _resolve_l2()
    projection = await _load_profile_projection(user_id)
    cached_payload = await _payload_from_cached_or_rebuilt_portrait(
        portrait_repo=portrait_repo,
        l2=l2,
        projection=projection,
        user_id=user_id,
    )
    if cached_payload is not None:
        return cached_payload

    observations = await _collect_fallback_observations(
        l2=l2,
        projection=projection,
        user_id=user_id,
    )
    fallback_projection = await _build_fallback_portrait_projection(
        l2=l2,
        projection=projection,
        user_id=user_id,
    )
    return _payload_from_fallback_projection(
        observations=observations,
        fallback_projection=fallback_projection,
    )


async def _load_profile_projection(user_id: str) -> Any:
    profile_repo = _resolve_profile_repo()
    if profile_repo is None:
        return None
    try:
        return await profile_repo.get(user_id)
    except Exception as exc:
        logger.debug("self portrait: profile lookup failed: %s", exc)
        return None


async def _payload_from_cached_or_rebuilt_portrait(
    *,
    portrait_repo: Any,
    l2: Any,
    projection: Any,
    user_id: str,
) -> dict[str, Any] | None:
    if portrait_repo is None:
        return None
    portrait_projection = await _load_portrait_projection(portrait_repo, user_id)
    if portrait_projection is None:
        return None
    is_stale = await portrait_projection_is_stale(
        portrait_projection,
        user_id=user_id,
        l2_store=l2,
        profile_projection=projection,
    )
    if not is_stale:
        return _payload_from_portrait_projection(portrait_projection)
    rebuilt = await _rebuild_portrait_projection(
        portrait_repo=portrait_repo,
        l2=l2,
        projection=projection,
        user_id=user_id,
    )
    return _payload_from_portrait_projection(rebuilt) if rebuilt is not None else None


async def _load_portrait_projection(portrait_repo: Any, user_id: str) -> Any:
    try:
        return await portrait_repo.get(user_id)
    except Exception as exc:
        logger.debug("self portrait: portrait projection lookup failed: %s", exc)
        return None


async def _rebuild_portrait_projection(
    *,
    portrait_repo: Any,
    l2: Any,
    projection: Any,
    user_id: str,
) -> Any:
    try:
        rebuilt = await UserPortraitProjectionBuilder(
            l2,
            profile_projection=projection,
        ).build(user_id)
        return await portrait_repo.upsert(rebuilt)
    except Exception as exc:
        logger.debug("self portrait: stale projection rebuild failed: %s", exc)
        return None


async def _collect_fallback_observations(
    *,
    l2: Any,
    projection: Any,
    user_id: str,
) -> list[UserPortraitObservation]:
    observations = _observations_from_projection(projection)
    if l2 is None:
        return observations

    snapshot = await _load_latest_tom_snapshot(l2, user_id)
    observations.extend(_observations_from_snapshot(snapshot))
    observations.extend(_observations_from_assertion_items(await _load_tom_assertions(l2, user_id)))
    observations.extend(await _load_graph_relationship_observations(l2, user_id))
    return observations


async def _load_latest_tom_snapshot(l2: Any, user_id: str) -> dict[str, Any] | None:
    try:
        snapshots = await l2.list_tom_snapshots(entity_id=f"user:{user_id}", limit=1)
    except Exception as exc:
        logger.debug("self portrait: tom snapshot lookup failed: %s", exc)
        return None
    return snapshots[0] if snapshots else None


async def _load_tom_assertions(l2: Any, user_id: str) -> list[dict[str, Any]]:
    try:
        return await l2.list_tom_assertions(
            entity_id=f"user:{user_id}",
            limit=50,
            offset=0,
        )
    except Exception as exc:
        logger.debug("self portrait: assertion lookup failed: %s", exc)
        return []


async def _load_graph_relationship_observations(
    l2: Any,
    user_id: str,
) -> list[UserPortraitObservation]:
    try:
        return await _observations_from_graph_relationships(l2, entity_id=f"user:{user_id}")
    except Exception as exc:
        logger.debug("self portrait: graph relationship lookup failed: %s", exc)
        return []


async def _build_fallback_portrait_projection(
    *,
    l2: Any,
    projection: Any,
    user_id: str,
) -> Any:
    try:
        return await UserPortraitProjectionBuilder(
            l2,
            profile_projection=projection,
        ).build(user_id)
    except Exception as exc:
        logger.debug("self portrait: fallback projection build failed: %s", exc)
        return None


def _payload_from_fallback_projection(
    *,
    observations: list[UserPortraitObservation],
    fallback_projection: Any,
) -> dict[str, Any]:
    is_cold_start = (
        not _projection_has_content(fallback_projection)
        if fallback_projection is not None
        else len(observations) == 0
    )
    payload = UserPortraitPayload(
        session_id="",
        persona_id="",
        topic="self",
        generated_at=int(time.time()),
        observations=observations,
        is_cold_start=is_cold_start,
        cold_start_line=None,
        cold_start_reason=("no_observations" if is_cold_start else None),
    )
    data = payload.to_dict()
    if fallback_projection is None:
        data["self_view"] = _build_self_view(observations)
        return data
    data["self_view"] = {
        "world": fallback_projection.world or _empty_world(),
        "review": fallback_projection.review or {"items": []},
        "recent": fallback_projection.recent or {"items": []},
    }
    data["prompt_summary"] = list(fallback_projection.prompt_summary)
    return data


def _payload_from_portrait_projection(portrait_projection: Any) -> dict[str, Any]:
    payload = UserPortraitPayload(
        session_id="",
        persona_id="",
        topic="self",
        generated_at=int(time.time()),
        observations=[],
        is_cold_start=False,
        cold_start_line=None,
        cold_start_reason=None,
    )
    data = payload.to_dict()
    data["self_view"] = {
        "world": portrait_projection.world or _empty_world(),
        "review": portrait_projection.review or {"items": []},
        "recent": portrait_projection.recent or {"items": []},
    }
    data["prompt_summary"] = list(portrait_projection.prompt_summary)
    return data


def _observations_from_projection(projection: Any) -> list[UserPortraitObservation]:
    if projection is None:
        return []

    facts: list[tuple[str, str, str]] = []
    if projection.real_name:
        facts.append((f"你叫 {projection.real_name}", "identity_profile", "real_name"))
    if projection.preferred_form_of_address:
        facts.append(
            (
                f"称呼你「{projection.preferred_form_of_address}」",
                "identity_profile",
                "preferred_form_of_address",
            )
        )
    if projection.home_location:
        facts.append(
            (
                f"住在{projection.home_location}",
                "identity_profile",
                "identity.location.home|claim_kind:identity_fact|world_group:identity",
            )
        )
    for key, value in (projection.preferences or {}).items():
        facts.append((
            f"偏好：{key} = {value}",
            "preference_profile",
            f"preference:{key}|claim_kind:preference_interest|world_group:preferences",
        ))
    for key, value in (projection.communication or {}).items():
        facts.append(
            (
                f"沟通风格：{key} = {value}",
                "communication_profile",
                f"communication:{key}|claim_kind:collaboration_style|world_group:work_style",
            )
        )
    for key, value in (projection.state or {}).items():
        facts.append((
            f"近期状态：{key} = {value}",
            "state_profile",
            f"state:{key}|claim_kind:recent_context|role:recent",
        ))

    observations: list[UserPortraitObservation] = []
    for text, family, ref in facts:
        basis_refs = [f"family:{family}"]
        basis_refs.extend(part for part in ref.split("|") if part)
        observations.append(
            UserPortraitObservation(
                kind="assertion",
                text=text,
                basis_count=1,
                basis_summary="user_profile_projection",
                basis_refs=basis_refs,
            )
        )
    return observations


def _observations_from_snapshot(snapshot: dict[str, Any] | None) -> list[UserPortraitObservation]:
    values = snapshot_recent_values(snapshot)
    if not values:
        return []
    snapshot_id = str((snapshot or {}).get("snapshot_id") or "tom-latest")
    basis_count = int((snapshot or {}).get("evidence_count") or 1)
    return [
        UserPortraitObservation(
            kind="reflection",
            text=text,
            basis_count=basis_count,
            basis_summary="L2 ToM snapshot",
            basis_refs=[snapshot_id],
        )
        for text in values
    ]


def _observations_from_assertion_items(
    items: list[dict[str, Any]],
) -> list[UserPortraitObservation]:
    if not items:
        return []
    obs: list[UserPortraitObservation] = []
    for item in items:
        decision = classify_assertion_portrait(item)
        role = decision.role
        if role == "skip":
            continue
        trait = str(item.get("trait_name") or item.get("predicate") or "")
        value = str(item.get("value") or item.get("trait_value") or "")
        if not trait or not value:
            continue
        refs: list[str] = [f"role:{role}"]
        assertion_id = str(item.get("assertion_id") or "").strip()
        if assertion_id:
            refs.append(f"assertion:{assertion_id}")
        refs.append(f"claim_kind:{decision.claim_kind}")
        if decision.world_group:
            refs.append(f"world_group:{decision.world_group}")
        for key, prefix in (
            ("trait_family", "family"),
            ("validation_state", "status"),
            ("source_domain", "source"),
        ):
            raw_value = str(item.get(key) or "").strip()
            if raw_value:
                refs.append(f"{prefix}:{raw_value}")
        obs.append(
            UserPortraitObservation(
                kind="assertion",
                text=f"{trait}: {value}",
                basis_count=int(item.get("evidence_count") or 1),
                basis_summary="L2 assertion",
                basis_refs=refs,
            )
        )
        if len(obs) >= 20:
            break
    return obs


async def _observations_from_graph_relationships(
    l2: Any,
    *,
    entity_id: str,
) -> list[UserPortraitObservation]:
    signals = await collect_portrait_graph_signals(l2, entity_id=entity_id)
    return [_observation_from_graph_signal(signal) for signal in signals]


def _observation_from_graph_signal(signal: PortraitGraphSignal) -> UserPortraitObservation:
    refs = [
        f"role:{signal.role}",
        f"claim_kind:{signal.claim_kind}",
        f"predicate:{signal.predicate}",
        f"object_type:{signal.object_type}",
    ]
    if signal.world_group:
        refs.append(f"world_group:{signal.world_group}")
    if signal.source_type:
        refs.append(f"source:{signal.source_type}")
    if signal.triple_id:
        refs.append(f"graph:{signal.triple_id}")

    return UserPortraitObservation(
        kind="relationship",
        text=signal.text,
        basis_count=signal.observation_count,
        basis_summary=(signal.source_type or "knowledge_graph"),
        basis_refs=refs,
    )


def _build_self_view(observations: list[UserPortraitObservation]) -> dict[str, Any]:
    world = _empty_world()
    groups = world["groups"]
    groups_by_id = {group["id"]: group for group in groups}
    review_items: list[dict[str, Any]] = []
    recent_items: list[dict[str, Any]] = []

    for index, observation in enumerate(observations):
        item = _self_view_item(observation, index)
        if _is_review_observation(observation):
            review_items.append(item)
            continue
        if _is_recent_observation(observation):
            recent_items.append(item)
            continue

        group_id = _world_group_id(observation)
        if group_id:
            groups_by_id[group_id]["items"].append(item)

    for group in groups:
        group["items"] = _dedupe_and_sort_world_items(group["items"])
        group["summary"] = _group_summary(group["id"], group["items"])

    return {
        "world": {**world, "total_count": len(observations), "groups": groups},
        "review": {
            "items": review_items,
        },
        "recent": {
            "items": recent_items,
        },
    }


def _empty_world() -> dict[str, Any]:
    return {
        "total_count": 0,
        "groups": [{"id": group_id, "items": []} for group_id in _WORLD_GROUP_IDS],
    }


def _self_view_item(observation: UserPortraitObservation, index: int) -> dict[str, Any]:
    source, source_key = _source_info(observation)
    assertion_id = _extract_assertion_id(observation)
    return {
        "id": f"{observation.kind}-{index}-{assertion_id or observation.text}",
        "text": _simplify_observation_text(observation.text),
        "source": source,
        "source_key": source_key,
        "assertion_id": assertion_id,
        "basis_count": observation.basis_count,
        "basis_refs": list(observation.basis_refs),
    }


def _is_review_observation(observation: UserPortraitObservation) -> bool:
    role = _ref_value(observation, "role")
    if role:
        return role == "review"
    state = _ref_value(observation, "status")
    return bool(state) and state in PORTRAIT_REVIEW_STATES


def _is_recent_observation(observation: UserPortraitObservation) -> bool:
    role = _ref_value(observation, "role")
    if role:
        return role == "recent"
    family = _ref_value(observation, "family")
    if family and family in PORTRAIT_RECENT_FAMILIES:
        return True
    return observation.kind == "reflection" or any(
        ref.startswith("state:") for ref in observation.basis_refs
    )


def _world_group_id(observation: UserPortraitObservation) -> str | None:
    explicit_group = _ref_value(observation, "world_group")
    if explicit_group in _WORLD_GROUP_IDS:
        return explicit_group
    claim_kind = _ref_value(observation, "claim_kind")
    if claim_kind == "identity_fact":
        return "identity"
    if claim_kind == "active_work":
        return "projects"
    if claim_kind == "preference_interest":
        return "preferences"
    if claim_kind == "collaboration_style":
        return "work_style"
    return None


def _projection_has_content(projection: Any) -> bool:
    if projection is None:
        return False
    world = getattr(projection, "world", {}) or {}
    review = getattr(projection, "review", {}) or {}
    recent = getattr(projection, "recent", {}) or {}
    if int(world.get("total_count") or 0) > 0:
        return True
    return bool((review.get("items") or []) or (recent.get("items") or []))


def _dedupe_and_sort_world_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_text: dict[str, dict[str, Any]] = {}
    for item in items:
        key = _world_item_key(item)
        if not key:
            continue
        previous = best_by_text.get(key)
        if previous is None or _world_item_strength(item) > _world_item_strength(previous):
            best_by_text[key] = item
    return sorted(
        best_by_text.values(),
        key=lambda item: (
            -_item_source_strength(item),
            -_item_validation_strength(item),
            -int(item.get("basis_count", 0) or 0),
            str(item.get("text") or "").casefold(),
        ),
    )


def _group_summary(group_id: str, items: list[dict[str, Any]]) -> str:
    texts = [
        str(item.get("text") or "").strip() for item in items if str(item.get("text") or "").strip()
    ]
    if not texts:
        return ""
    short = texts[:4]
    if group_id == "identity":
        return "；".join(short)
    if group_id == "projects":
        return f"长期推进或反复关注：{'、'.join(short)}"
    if group_id == "preferences":
        return f"关注或偏好：{'、'.join(short)}"
    if group_id == "work_style":
        return f"工作和沟通方式：{'、'.join(short)}"
    return "、".join(short)


def _world_item_key(item: dict[str, Any]) -> str:
    return re.sub(r"\s+", " ", str(item.get("text") or "").strip()).casefold()


def _world_item_strength(item: dict[str, Any]) -> tuple[int, int, int, str]:
    return (
        _item_source_strength(item),
        _item_validation_strength(item),
        int(item.get("basis_count", 0) or 0),
        str(item.get("assertion_id") or ""),
    )


def _item_source_strength(item: dict[str, Any]) -> int:
    source_key = item.get("source_key")
    if isinstance(source_key, str) and source_key:
        return PORTRAIT_SOURCE_STRENGTH.get(source_key, 0)
    for ref in item.get("basis_refs") or []:
        if not isinstance(ref, str) or not ref.startswith("source:"):
            continue
        source = _normalize_source_key(ref.removeprefix("source:"))
        return PORTRAIT_SOURCE_STRENGTH.get(source, 0)
    return 0


def _item_validation_strength(item: dict[str, Any]) -> int:
    for ref in item.get("basis_refs") or []:
        if not isinstance(ref, str) or not ref.startswith("status:"):
            continue
        state = ref.removeprefix("status:").strip().casefold()
        return PORTRAIT_VALIDATION_STRENGTH.get(state, 0)
    return 0


def _extract_assertion_id(observation: UserPortraitObservation) -> str | None:
    for ref in observation.basis_refs:
        if ref.startswith("assertion:"):
            value = ref.removeprefix("assertion:").strip()
            return value or None
        compact = ref.replace("-", "")
        if len(ref) >= _ASSERTION_REF_MIN_LENGTH and all(
            c in "0123456789abcdefABCDEF" for c in compact
        ):
            return ref
    return None


def _ref_value(observation: UserPortraitObservation, prefix: str) -> str | None:
    needle = f"{prefix}:"
    for ref in observation.basis_refs:
        if ref.startswith(needle):
            value = ref.removeprefix(needle).strip()
            return value or None
    return None


def _simplify_observation_text(text: str) -> str:
    trimmed = text.strip()
    eq_index = trimmed.rfind(" = ")
    if eq_index >= 0:
        return trimmed[eq_index + 3 :].strip()
    colon_index = trimmed.find(": ")
    if colon_index >= 0:
        return trimmed[colon_index + 2 :].strip()
    for prefix in ("偏好：", "沟通风格：", "近期状态：", "常用工具："):
        if trimmed.startswith(prefix):
            return trimmed.removeprefix(prefix).strip()
    return trimmed


def _source_info(observation: UserPortraitObservation) -> tuple[str, str | None]:
    source = _ref_value(observation, "source")
    if source:
        source_key = _normalize_source_key(source)
        if source_key in _INTERNAL_SOURCE_KEYS:
            return "", None
        return source.replace("-", " "), source_key

    basis_summary = observation.basis_summary.strip()
    if basis_summary and basis_summary.lower() != "l2 assertion":
        if basis_summary.lower() == "l2 tom snapshot":
            return "tom", "tom"
        return basis_summary, _normalize_source_key(basis_summary)
    return "", None


def _normalize_source_key(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")
