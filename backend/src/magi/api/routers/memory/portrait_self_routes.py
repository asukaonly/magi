"""GET /api/memory/portrait/self — global self-portrait without LLM rendering."""

from __future__ import annotations

import logging
import re
import time
from contextlib import contextmanager
from inspect import isawaitable
from typing import Any

from fastapi import APIRouter, Query

from ....memory.l2.entities.catalog.lookup import get_canonical_names
from ....memory.portrait.contracts import PortraitObservation, PortraitPayload
from ....memory.provider import get_unified_memory
from ....user_profile.projection_repository import UserProfileProjectionRepository


logger = logging.getLogger(__name__)


_ASSERTION_REF_MIN_LENGTH = 20
_WORLD_GROUP_IDS = ("identity", "preferences", "routine", "places", "communication")
_FAMILY_WORLD_GROUPS = {
    "identity_profile": "identity",
    "preference_profile": "preferences",
    "routine_profile": "routine",
    "communication_profile": "communication",
}
_GRAPH_WORLD_RULES = {
    "VISITED": {
        "group": "places",
        "object_types": {"place"},
        "min_observations": 2,
    },
    "OWNS": {
        "group": "routine",
        "object_types": {"hardware", "product"},
        "min_observations": 2,
    },
    "USES": {
        "group": "routine",
        "object_types": {"software", "hardware", "technology", "product"},
        "min_observations": 3,
    },
}
_RECENT_FAMILIES = {
    "state_profile",
    "mood",
    "stress",
    "engagement",
    "trigger",
    "relationship_shift",
    "group_atmosphere",
}
_REVIEW_STATES = {"tentative", "contradicted"}
_INTERNAL_SOURCE_KEYS = {"external_activity"}


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

        if l2 is not None:
            try:
                observations.extend(await _observations_from_graph_relationships(
                    l2,
                    entity_id=f"user:{user_id}",
                ))
            except Exception as exc:
                logger.debug("self portrait: graph relationship lookup failed: %s", exc)

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
        data = payload.to_dict()
        data["self_view"] = _build_self_view(observations)
        return data

    return router


def _observations_from_projection(projection: Any) -> list[PortraitObservation]:
    if projection is None:
        return []

    facts: list[tuple[str, str, str]] = []
    if projection.real_name:
        facts.append((f"你叫 {projection.real_name}", "identity_profile", "real_name"))
    if projection.preferred_form_of_address:
        facts.append((
            f"称呼你「{projection.preferred_form_of_address}」",
            "identity_profile",
            "preferred_form_of_address",
        ))
    if projection.home_location:
        facts.append((f"住在{projection.home_location}", "identity_profile", "home_location"))
    for key, value in (projection.preferences or {}).items():
        facts.append((f"偏好：{key} = {value}", "preference_profile", f"preference:{key}"))
    for key, value in (projection.communication or {}).items():
        facts.append((f"沟通风格：{key} = {value}", "communication_profile", f"communication:{key}"))
    for key, value in (projection.state or {}).items():
        facts.append((f"近期状态：{key} = {value}", "state_profile", f"state:{key}"))

    return [
        PortraitObservation(
            kind="assertion",
            text=text,
            basis_count=1,
            basis_summary="user_profile_projection",
            basis_refs=[f"family:{family}", ref],
        )
        for text, family, ref in facts
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
        refs: list[str] = []
        assertion_id = str(item.get("assertion_id") or "").strip()
        if assertion_id:
            refs.append(f"assertion:{assertion_id}")
        for key, prefix in (
            ("trait_family", "family"),
            ("validation_state", "status"),
            ("source_domain", "source"),
        ):
            raw_value = str(item.get(key) or "").strip()
            if raw_value:
                refs.append(f"{prefix}:{raw_value}")
        obs.append(PortraitObservation(
            kind="assertion",
            text=f"{trait}: {value}",
            basis_count=int(item.get("evidence_count") or 1),
            basis_summary="L2 assertion",
            basis_refs=refs,
        ))
    return obs


async def _observations_from_graph_relationships(
    l2: Any,
    *,
    entity_id: str,
) -> list[PortraitObservation]:
    getter = getattr(l2, "get_relationships", None)
    if not callable(getter):
        return []

    result = getter(
        subject_id=entity_id,
        predicates=list(_GRAPH_WORLD_RULES),
        status="active",
        limit=80,
    )
    if not isawaitable(result):
        return []
    relationships = await result
    if not isinstance(relationships, list) or not relationships:
        return []

    object_ids = [
        str(edge.get("object_id") or "").strip()
        for edge in relationships
        if isinstance(edge, dict) and str(edge.get("object_id") or "").strip()
    ]
    canonical_names: dict[str, str] = {}
    db_path = getattr(l2, "db_path", None)
    if isinstance(db_path, str) and db_path.strip() and object_ids:
        try:
            canonical_names = await get_canonical_names(db_path, object_ids)
        except Exception as exc:
            logger.debug("self portrait: graph canonical name lookup failed: %s", exc)

    observations: list[PortraitObservation] = []
    seen: set[tuple[str, str]] = set()
    for edge in relationships:
        if not isinstance(edge, dict):
            continue
        observation = _observation_from_graph_relationship(edge, canonical_names)
        if observation is None:
            continue
        group_id = _ref_value(observation, "world_group") or ""
        key = (group_id, observation.text.casefold())
        if key in seen:
            continue
        seen.add(key)
        observations.append(observation)
        if len(observations) >= 12:
            break
    return observations


def _observation_from_graph_relationship(
    edge: dict[str, Any],
    canonical_names: dict[str, str],
) -> PortraitObservation | None:
    predicate = str(edge.get("predicate") or "").strip().upper()
    rule = _GRAPH_WORLD_RULES.get(predicate)
    if rule is None:
        return None
    if int(edge.get("observation_count", 0) or 0) < int(rule["min_observations"]):
        return None

    object_type = str(edge.get("object_type") or "").strip().casefold()
    object_types = rule["object_types"]
    if object_type not in object_types:
        return None

    text = _graph_object_name(edge=edge, canonical_names=canonical_names)
    if not text:
        return None

    refs = [
        f"world_group:{rule['group']}",
        f"predicate:{predicate}",
        f"object_type:{object_type}",
    ]
    source_type = str(edge.get("source_type") or "").strip()
    if source_type:
        refs.append(f"source:{source_type}")
    triple_id = str(edge.get("triple_id") or "").strip()
    if triple_id:
        refs.append(f"graph:{triple_id}")

    return PortraitObservation(
        kind="relationship",
        text=text,
        basis_count=int(edge.get("observation_count") or 1),
        basis_summary=(source_type or "knowledge_graph"),
        basis_refs=refs,
    )


def _graph_object_name(
    *,
    edge: dict[str, Any],
    canonical_names: dict[str, str],
) -> str:
    object_id = str(edge.get("object_id") or "").strip()
    raw_name = canonical_names.get(object_id, "") if object_id else ""
    if not raw_name:
        raw_name = _object_slug(object_id)
    name = raw_name.replace("_", " ").strip()
    if not name:
        return ""
    if _LOW_VALUE_GRAPH_NAME_RE.fullmatch(name):
        return ""
    return name[:80]


_LOW_VALUE_GRAPH_NAME_RE = re.compile(r"[0-9a-f]{10,}", re.IGNORECASE)


def _object_slug(object_id: str) -> str:
    if ":" in object_id:
        return object_id.split(":", 1)[1]
    return object_id


def _build_self_view(observations: list[PortraitObservation]) -> dict[str, Any]:
    groups = [{"id": group_id, "items": []} for group_id in _WORLD_GROUP_IDS]
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

    return {
        "world": {
            "total_count": len(observations),
            "groups": groups,
        },
        "review": {
            "items": review_items,
        },
        "recent": {
            "items": recent_items,
        },
    }


def _self_view_item(observation: PortraitObservation, index: int) -> dict[str, Any]:
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


def _is_review_observation(observation: PortraitObservation) -> bool:
    state = _ref_value(observation, "status")
    if state:
        return state in _REVIEW_STATES
    return bool(_extract_assertion_id(observation)) and observation.basis_summary.lower() == "l2 assertion"


def _is_recent_observation(observation: PortraitObservation) -> bool:
    family = _ref_value(observation, "family")
    if family and family in _RECENT_FAMILIES:
        return True
    return observation.kind == "reflection" or any(
        ref.startswith("state:") for ref in observation.basis_refs
    )


def _world_group_id(observation: PortraitObservation) -> str | None:
    explicit_group = _ref_value(observation, "world_group")
    if explicit_group in _WORLD_GROUP_IDS:
        return explicit_group
    family = _ref_value(observation, "family")
    return _FAMILY_WORLD_GROUPS.get(family or "")


def _extract_assertion_id(observation: PortraitObservation) -> str | None:
    for ref in observation.basis_refs:
        if ref.startswith("assertion:"):
            value = ref.removeprefix("assertion:").strip()
            return value or None
        compact = ref.replace("-", "")
        if len(ref) >= _ASSERTION_REF_MIN_LENGTH and all(c in "0123456789abcdefABCDEF" for c in compact):
            return ref
    return None


def _ref_value(observation: PortraitObservation, prefix: str) -> str | None:
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
        return trimmed[eq_index + 3:].strip()
    colon_index = trimmed.find(": ")
    if colon_index >= 0:
        return trimmed[colon_index + 2:].strip()
    for prefix in ("偏好：", "沟通风格：", "近期状态：", "常用工具："):
        if trimmed.startswith(prefix):
            return trimmed.removeprefix(prefix).strip()
    return trimmed


def _source_info(observation: PortraitObservation) -> tuple[str, str | None]:
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
