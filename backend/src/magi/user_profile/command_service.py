"""Write facade for user-authored profile settings."""

from __future__ import annotations

import json
import time
from typing import Any

from ..core.logger import get_logger
from ..memory.event_contracts import (
    IngestTarget,
    MemoryDomain,
    MemoryEvent,
    RetentionClass,
    TomDepth,
    generate_event_id,
)
from .derivation import derive_birth_year, parse_iso_date
from .models import DEFAULT_USER_ID, ProfileUpdatePatch, UserProfileProjection
from .query_service import UserProfileQueryService

logger = get_logger(__name__)


class UserProfileCommandService:
    """Persist settings edits as L2 assertions and refresh the projection."""

    def __init__(
        self,
        *,
        unified_memory: Any,
        query_service: UserProfileQueryService,
        portrait_repository: Any = None,
        portrait_builder: Any = None,
    ):
        self._unified_memory = unified_memory
        self._query_service = query_service
        self._portrait_repository = portrait_repository
        self._portrait_builder = portrait_builder

    async def update_from_settings(
        self,
        patch: ProfileUpdatePatch,
        *,
        user_id: str = DEFAULT_USER_ID,
    ) -> UserProfileProjection:
        updates = patch.model_dump(exclude_unset=True)
        if not updates:
            return await self._query_service.get_current_profile(user_id)

        event_id = await self._write_profile_update_event(user_id=user_id, updates=updates)
        candidates = self._build_assertion_candidates(
            user_id=user_id,
            updates=updates,
            evidence_event_ids=[event_id] if event_id else [],
        )
        l2 = getattr(self._unified_memory, "l2", None)
        if l2 is None:
            raise RuntimeError("L2 store is not initialized")
        for candidate in candidates:
            assertion_id = await l2.upsert_assertion_candidate(candidate)
            await l2.apply_user_feedback(assertion_id=assertion_id, feedback="confirmed")
        return await self.refresh_from_memory(user_id)

    async def refresh_from_memory(self, user_id: str = DEFAULT_USER_ID) -> UserProfileProjection:
        profile = await self._query_service.refresh_profile(user_id)
        await self._refresh_portrait(user_id, profile)
        return profile

    async def _refresh_portrait(self, user_id: str, profile: UserProfileProjection) -> None:
        if self._portrait_repository is None or self._portrait_builder is None:
            return
        try:
            builder = self._portrait_builder
            with_profile_projection = getattr(builder, "with_profile_projection", None)
            if callable(with_profile_projection):
                builder = with_profile_projection(profile)
            portrait = await builder.build(user_id)
            await self._portrait_repository.upsert(portrait)
        except Exception as exc:
            logger.debug("Failed to refresh portrait projection for %s: %s", user_id, exc)

    async def _write_profile_update_event(self, *, user_id: str, updates: dict[str, Any]) -> str | None:
        if getattr(self._unified_memory, "l1", None) is None:
            return None
        now = time.time()
        event_id = generate_event_id(prefix="profile_update")
        event = MemoryEvent(
            event_id=event_id,
            correlation_id=event_id,
            timestamp=now,
            created_at=now,
            event_type="profile.settings_update",
            source="settings_profile",
            source_item_id=None,
            memory_domain=MemoryDomain.USER_AUTHORED,
            ingest_target=IngestTarget.L1_ONLY,
            cognition_eligible=False,
            tom_depth=TomDepth.NONE,
            retention_class=RetentionClass.PERMANENT,
            session_id=None,
            turn_id=None,
            user_id=user_id,
            task_id=None,
            content=json.dumps({"profile_update": updates}, ensure_ascii=False, sort_keys=True),
            author_type="user",
            content_type="text",
            importance_score=0.8,
            level=1,
            metadata_json={"source": "personal_profile_settings"},
        )
        return await self._unified_memory.store_governed_l1_event(event)

    def _build_assertion_candidates(
        self,
        *,
        user_id: str,
        updates: dict[str, Any],
        evidence_event_ids: list[str],
    ) -> list[dict[str, Any]]:
        now = time.time()
        entity_id = f"user:{user_id}"
        candidates: list[dict[str, Any]] = []

        def add(trait_family: str, trait_name: str, value: Any) -> None:
            trait_value = json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (list, dict)) else str(value or "")
            candidates.append(
                {
                    "entity_id": entity_id,
                    "entity_type": "user",
                    "trait_family": trait_family,
                    "trait_name": trait_name,
                    "trait_value": trait_value,
                    "confidence_score": 1.0,
                    "evidence_events": evidence_event_ids,
                    "volatility_index": 0.05,
                    "source_domain": "settings_profile",
                    "inference_depth": "explicit",
                    "validation_state": "stable",
                    "first_inferred_at": now,
                    "last_validated_at": now,
                    "target_entity_id": "",
                    "target_entity_type": "",
                    "target_scope": "global",
                    "temporal_scope": "stable",
                    "decay_policy": None,
                    "decay_anchor_at": now,
                    "context_ref_id": "",
                    "expires_at": None,
                    "memory_subdomain": "semantic",
                    "natural_summary": f"User profile field {trait_name} was set from personal profile settings.",
                }
            )

        if "real_name" in updates:
            add("identity_profile", "identity.real_name", updates.get("real_name"))
        if "birth_date" in updates:
            birth_date_text = str(updates.get("birth_date") or "").strip()
            if birth_date_text and parse_iso_date(birth_date_text) is None:
                raise ValueError("birth_date must use YYYY-MM-DD format")
            add("identity_profile", "identity.birth_date", birth_date_text)
            birth_year = derive_birth_year(parse_iso_date(birth_date_text))
            if birth_year is not None:
                add("identity_profile", "identity.birth_year", birth_year)
        if "home_location" in updates:
            add("identity_profile", "identity.location.home", updates.get("home_location"))
        if "preferred_form_of_address" in updates:
            add(
                "communication_profile",
                "communication.address.preferred",
                updates.get("preferred_form_of_address"),
            )
        if "disallowed_forms_of_address" in updates:
            add(
                "communication_profile",
                "communication.address.disallowed",
                [str(item).strip() for item in updates.get("disallowed_forms_of_address") or [] if str(item).strip()],
            )
        return candidates
