"""User-profile rebuild handlers for memory correction jobs."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from ..memory.l2.corrections.repository import MemoryCorrectionRepository
from .portrait_projection_builder import UserPortraitProjectionBuilder
from .portrait_projection_repository import UserPortraitProjectionRepository
from .projection_builder import UserProfileProjectionBuilder
from .projection_repository import UserProfileProjectionRepository

CorrectionDerivationHandler = Callable[[Mapping[str, Any]], Awaitable[None]]


class UserProfileCorrectionDerivationHandlers:
    """Rebuild profile projections while the memory layer owns job control."""

    def __init__(self, *, db_path: str, l2_store: Any) -> None:
        self._db_path = str(db_path)
        self._l2_store = l2_store
        self._repository = MemoryCorrectionRepository(self._db_path)

    def as_mapping(self) -> dict[str, CorrectionDerivationHandler]:
        return {
            "profile": self.rebuild_profile,
            "portrait": self.rebuild_portrait,
        }

    async def rebuild_profile(self, job: Mapping[str, Any]) -> None:
        entity_id = str(job["target_key"])
        user_id = _user_id(entity_id)
        if user_id is None:
            return
        projection = await UserProfileProjectionBuilder(self._l2_store).build(user_id)
        stored = await UserProfileProjectionRepository(self._db_path).upsert(projection)
        await self._repository.replace_dependencies(
            artifact_kind="profile",
            artifact_id=user_id,
            subject_key=entity_id,
            source_revision=int(job["target_revision"]),
            sources=[
                ("assertion", assertion_id)
                for assertion_id in _collect_assertion_ids(stored.field_sources)
            ],
        )

    async def rebuild_portrait(self, job: Mapping[str, Any]) -> None:
        entity_id = str(job["target_key"])
        user_id = _user_id(entity_id)
        if user_id is None:
            return
        profile = await UserProfileProjectionRepository(self._db_path).get(user_id)
        projection = await UserPortraitProjectionBuilder(
            self._l2_store,
            profile_projection=profile,
        ).build(user_id)
        stored = await UserPortraitProjectionRepository(self._db_path).upsert(projection)
        sources = [
            ("assertion", reference.split(":", 1)[1])
            for reference in stored.evidence_refs
            if reference.startswith("assertion:")
        ]
        await self._repository.replace_dependencies(
            artifact_kind="portrait",
            artifact_id=user_id,
            subject_key=entity_id,
            source_revision=int(job["target_revision"]),
            sources=sources,
        )


def build_user_profile_correction_derivation_handlers(
    *,
    db_path: str,
    l2_store: Any,
) -> dict[str, CorrectionDerivationHandler]:
    """Build handlers that can be injected into the memory job runner."""

    return UserProfileCorrectionDerivationHandlers(
        db_path=db_path,
        l2_store=l2_store,
    ).as_mapping()


def register_user_profile_correction_derivation_handlers(
    unified_memory: Any,
) -> None:
    """Register profile rebuild handlers on an initialized L2 store."""

    l2_store = getattr(unified_memory, "l2", None)
    if l2_store is None:
        return
    register = getattr(l2_store, "register_memory_correction_job_handler", None)
    db_path = str(getattr(l2_store, "db_path", "") or "").strip()
    if not callable(register) or not db_path:
        return
    for job_kind, handler in build_user_profile_correction_derivation_handlers(
        db_path=db_path,
        l2_store=l2_store,
    ).items():
        register(job_kind, handler)


def _user_id(subject_key: str) -> str | None:
    if not subject_key.startswith("user:"):
        return None
    value = subject_key.split(":", 1)[1].strip()
    return value or None


def _collect_assertion_ids(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        assertion_id = str(value.get("assertion_id") or "").strip()
        if assertion_id:
            found.append(assertion_id)
        for nested in value.values():
            found.extend(_collect_assertion_ids(nested))
    elif isinstance(value, (list, tuple)):
        for nested in value:
            found.extend(_collect_assertion_ids(nested))
    return list(dict.fromkeys(found))


__all__ = [
    "CorrectionDerivationHandler",
    "UserProfileCorrectionDerivationHandlers",
    "build_user_profile_correction_derivation_handlers",
    "register_user_profile_correction_derivation_handlers",
]
