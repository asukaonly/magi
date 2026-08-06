"""Async user-profile service backed by L2 cognition stores.

Provides display-name and preference lookups that the prompt assembler
injects into context.  Falls back to safe defaults when L2 is unavailable
or the user entity does not exist yet.

Results are cached per user_id with a configurable TTL to avoid redundant
SQLite round-trips during prompt assembly.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict

from ..core.logger import get_logger
from ..memory.l2.corrections.cache_signals import subject_change_signal
from ..user_profile.portrait_projection_builder import UserPortraitProjectionBuilder
from ..user_profile.portrait_projection_freshness import portrait_projection_is_stale
from ..user_profile.portrait_projection_repository import UserPortraitProjectionRepository
from ..user_profile.projection_builder import UserProfileProjectionBuilder
from ..user_profile.projection_freshness import profile_projection_is_stale
from ..user_profile.projection_repository import UserProfileProjectionRepository
from ..user_profile.query_service import UserProfileQueryService

logger = get_logger(__name__)

_DEFAULT_CACHE_TTL = 300  # 5 minutes
_DEFAULT_EMPTY_CACHE_TTL = 5  # Refresh empty profile reads quickly while L2 catches up.
_DEFAULT_ERROR_CACHE_TTL = 5
_ADDRESS_PREFERRED_KEY = "address.preferred"
_ADDRESS_DISALLOWED_KEY = "address.disallowed"
_ADDRESS_REAL_NAME_KEY = "address.real_name"
_PROFILE_ASSERTION_FAMILIES = ["preference_profile"]
_PROFILE_ASSERTION_STATES = ["stable", "corroborated", "tentative"]


@dataclass
class _CacheEntry:
    display_name: str = "unknown"
    preferences: Dict[str, Any] = field(default_factory=dict)
    prompt_summary: list[str] = field(default_factory=list)
    correction_signal: int = 0
    source_revision: int | None = None
    dependency_error: bool = False
    fetched_at: float = 0.0


class UserProfileService:
    """Thin async facade over L2 entity catalog + ToM snapshots.

    Maintains a lightweight in-memory TTL cache keyed by ``user_id`` so that
    repeated calls within the same prompt-assembly cycle (or across
    back-to-back messages) do not issue duplicate DB queries.
    """

    def __init__(
        self,
        unified_memory=None,
        cache_ttl: float = _DEFAULT_CACHE_TTL,
        empty_cache_ttl: float = _DEFAULT_EMPTY_CACHE_TTL,
    ):
        self._unified_memory = unified_memory
        self._cache_ttl = cache_ttl
        self._empty_cache_ttl = max(0.0, float(empty_cache_ttl))
        self._cache: Dict[str, _CacheEntry] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_display_name(self, user_id: str) -> str:
        """Return the canonical display name for *user_id* from L2 entity catalog."""
        entry = await self._get_cached(user_id)
        return entry.display_name

    async def get_preference_summary(self, user_id: str) -> Dict[str, Any]:
        """Return aggregated user preferences from L2 ToM snapshot."""
        entry = await self._get_cached(user_id)
        return dict(entry.preferences)

    async def get_portrait_prompt_summary(self, user_id: str) -> list[str]:
        """Return clean user-understanding lines for prompt injection."""
        entry = await self._get_cached(user_id)
        return list(entry.prompt_summary)

    def invalidate(self, user_id: str | None = None) -> None:
        """Drop cached data for *user_id*, or all entries if ``None``."""
        if user_id is None:
            self._cache.clear()
        else:
            self._cache.pop(user_id, None)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _get_cached(self, user_id: str) -> _CacheEntry:
        """Return a cache entry, fetching from L2 if stale or missing."""
        if not user_id:
            return _CacheEntry()

        now = time.monotonic()
        entry = self._cache.get(user_id)
        current_signal = subject_change_signal(
            self._memory_db_path(),
            f"user:{user_id}",
        )
        revision_supported, current_revision = await self._current_source_revision(user_id)
        if (
            entry is not None
            and entry.correction_signal == current_signal
            and (
                not revision_supported
                or (
                    current_revision is not None
                    and entry.source_revision == current_revision
                )
                or (current_revision is None and entry.dependency_error)
            )
            and (now - entry.fetched_at) < self._ttl_for_entry(entry)
        ):
            return entry

        for read_attempt in range(2):
            entry = await self._fetch_entry(
                user_id,
                fetched_at=now,
                correction_signal=current_signal,
            )
            completed_supported, completed_revision = await self._current_source_revision(
                user_id
            )
            revision_supported = revision_supported or completed_supported
            entry.source_revision = completed_revision
            entry.dependency_error = revision_supported and completed_revision is None
            if (
                not revision_supported
                or current_revision is None
                or completed_revision is None
                or current_revision == completed_revision
            ):
                self._cache[user_id] = entry
                return entry
            if read_attempt == 0:
                current_revision = completed_revision
                now = time.monotonic()

        logger.warning(
            "Discarded user profile read because the source revision kept changing",
            user_id=user_id,
        )
        return _CacheEntry()

    async def _fetch_entry(
        self,
        user_id: str,
        *,
        fetched_at: float,
        correction_signal: int,
    ) -> _CacheEntry:
        entry = _CacheEntry(
            fetched_at=fetched_at,
            correction_signal=correction_signal,
        )
        prompt_summary = await self._fetch_portrait_prompt_summary(user_id)
        projection_entry = await self._fetch_projection_entry(user_id)
        if projection_entry is not None:
            entry = projection_entry
            entry.fetched_at = fetched_at
            entry.correction_signal = correction_signal
        else:
            entry.preferences = await self._fetch_preferences(user_id)
            entry.display_name = await self._fetch_display_name(
                user_id,
                preferences=entry.preferences,
            )
        entry.prompt_summary = prompt_summary
        return entry

    async def _current_source_revision(self, user_id: str) -> tuple[bool, int | None]:
        l2 = getattr(self._unified_memory, "l2", None)
        getter = getattr(l2, "current_subject_revision", None)
        if not callable(getter):
            return False, None
        try:
            return True, int(await getter(f"user:{user_id}"))
        except Exception as exc:
            logger.error(
                "User profile source revision read failed",
                user_id=user_id,
                projection_kind="profile",
                stage="source_revision",
                cached_kept=user_id in self._cache,
                error_type=type(exc).__name__,
            )
            return True, None

    async def _fetch_portrait_prompt_summary(self, user_id: str) -> list[str]:
        db_path = self._memory_db_path()
        if not db_path:
            return []
        repo = UserPortraitProjectionRepository(db_path)
        try:
            projection = await repo.get(user_id)
        except Exception as exc:
            _log_prompt_projection_failure(
                user_id=user_id,
                stage="cache_lookup",
                error=exc,
                cached_kept=False,
            )
            return []
        cached_projection = projection
        l2 = getattr(self._unified_memory, "l2", None) if self._unified_memory is not None else None
        if l2 is None:
            return [line for line in projection.prompt_summary if str(line).strip()] if projection is not None else []
        try:
            profile_projection = await self._current_profile_projection(user_id)
        except Exception as exc:
            _log_prompt_projection_failure(
                user_id=user_id,
                stage="profile_freshness",
                error=exc,
                cached_kept=projection is not None,
            )
            return _prompt_lines(projection)
        try:
            is_stale = (
                projection is not None
                and await portrait_projection_is_stale(
                    projection,
                    user_id=user_id,
                    l2_store=l2,
                    profile_projection=profile_projection,
                )
            )
        except Exception as exc:
            _log_prompt_projection_failure(
                user_id=user_id,
                stage="freshness",
                error=exc,
                cached_kept=projection is not None,
            )
            return _prompt_lines(projection)
        if projection is None or is_stale:
            try:
                projection = await UserPortraitProjectionBuilder(
                    l2,
                    profile_projection=profile_projection,
                ).build(user_id)
                projection = await repo.upsert(projection)
            except Exception as exc:
                _log_prompt_projection_failure(
                    user_id=user_id,
                    stage="rebuild",
                    error=exc,
                    cached_kept=cached_projection is not None,
                )
                return _prompt_lines(cached_projection)
        return _prompt_lines(projection)

    async def _fetch_projection_entry(self, user_id: str) -> _CacheEntry | None:
        db_path = self._memory_db_path()
        if not db_path:
            return None
        try:
            projection = await self._current_profile_projection(user_id)
        except Exception as exc:
            logger.error(
                "User profile prompt projection input failed",
                user_id=user_id,
                projection_kind="profile",
                stage="read",
                cached_kept=True,
                error_type=type(exc).__name__,
            )
            return None
        if projection is None:
            return None
        preferences: Dict[str, Any] = {
            "identity.real_name": projection.real_name,
            "communication.address.preferred": projection.preferred_form_of_address,
        }
        if projection.birth_date:
            preferences["identity.birth_date"] = projection.birth_date
        if projection.birth_year is not None:
            preferences["identity.birth_year"] = projection.birth_year
        if projection.age_years is not None:
            preferences["identity.age_years"] = projection.age_years
        if projection.home_location:
            preferences["identity.location.home"] = projection.home_location
        disallowed = projection.communication.get("disallowed_forms_of_address")
        if disallowed:
            preferences["communication.address.disallowed"] = disallowed
        l2 = getattr(self._unified_memory, "l2", None)
        if l2 is not None:
            assertion_preferences = await self._fetch_assertion_preferences(
                l2=l2,
                entity_id=f"user:{user_id}",
            )
            for key, value in assertion_preferences.items():
                preferences.setdefault(key, value)
        return _CacheEntry(
            display_name=projection.display_name or "unknown",
            preferences={key: value for key, value in preferences.items() if value not in (None, "")},
        )

    async def _current_profile_projection(self, user_id: str):
        db_path = self._memory_db_path()
        if not db_path:
            return None
        repository = UserProfileProjectionRepository(db_path)
        l2 = getattr(self._unified_memory, "l2", None)
        if l2 is None:
            return await repository.get(user_id)
        service = UserProfileQueryService(
            repository=repository,
            builder=UserProfileProjectionBuilder(l2),
        )
        projection = await service.get_current_profile(user_id)
        if await profile_projection_is_stale(
            projection,
            user_id=user_id,
            l2_store=l2,
        ):
            raise RuntimeError("User profile projection remained stale after refresh")
        return projection

    def _memory_db_path(self) -> str:
        if self._unified_memory is None:
            return ""
        l2 = getattr(self._unified_memory, "l2", None)
        return str(getattr(l2, "db_path", "") or "") if l2 is not None else ""

    async def _fetch_display_name(self, user_id: str, *, preferences: Dict[str, Any] | None = None) -> str:
        preferred_name = self._derive_display_name(preferences or {})
        if preferred_name:
            return preferred_name

        if self._unified_memory is None:
            return "unknown"

        catalog = getattr(self._unified_memory, "l2_entity_catalog", None)
        if catalog is None:
            return "unknown"

        entity_id = f"user:{user_id}"
        try:
            entities = await catalog.list_entities(entity_ids=[entity_id])
            if entities:
                name = entities[0].get("canonical_name", "")
                if name:
                    return name
        except Exception:
            logger.debug("Failed to look up display name for %s", user_id)

        return "unknown"

    async def _fetch_preferences(self, user_id: str) -> Dict[str, Any]:
        if self._unified_memory is None:
            return {}

        l2 = getattr(self._unified_memory, "l2", None)
        if l2 is None:
            return {}

        entity_id = f"user:{user_id}"
        snapshot_preferences: Dict[str, Any] = {}
        try:
            snapshot = await l2.get_tom_snapshot(
                entity_id=entity_id,
                entity_type="user",
            )
            if snapshot is not None:
                snapshot_preferences = self._normalize_preferences(dict(snapshot.get("preferences", {}) or {}))
        except Exception:
            logger.debug("Failed to get preference summary for %s", user_id)

        assertion_preferences = await self._fetch_assertion_preferences(
            l2=l2,
            entity_id=entity_id,
        )
        if not assertion_preferences:
            return snapshot_preferences

        if not snapshot_preferences:
            return assertion_preferences

        merged = dict(snapshot_preferences)
        for key, value in assertion_preferences.items():
            merged.setdefault(key, value)
        return merged

    async def _fetch_assertion_preferences(self, *, l2: Any, entity_id: str) -> Dict[str, Any]:
        list_assertions = getattr(l2, "list_current_assertions", None)
        if list_assertions is None:
            return {}

        try:
            assertions = await list_assertions(
                entity_id=entity_id,
                entity_type="user",
                context_scope=None,
                limit=200,
            )
        except Exception:
            logger.debug("Failed to get preference assertions for %s", entity_id)
            return {}

        preferences: Dict[str, Any] = {}
        for assertion in assertions:
            if assertion.get("trait_family") not in _PROFILE_ASSERTION_FAMILIES:
                continue
            if assertion.get("validation_state") not in _PROFILE_ASSERTION_STATES:
                continue
            raw_trait_name = str(assertion.get("trait_name") or "").strip()
            if not raw_trait_name:
                continue
            preference_key = raw_trait_name.split(".", 1)[1] if raw_trait_name.startswith("preference.") else raw_trait_name
            if not preference_key or preference_key in preferences:
                continue
            preferences[preference_key] = self._normalize_preference_value(assertion.get("trait_value"))
        return preferences

    def _ttl_for_entry(self, entry: _CacheEntry) -> float:
        if entry.dependency_error:
            return min(self._cache_ttl, _DEFAULT_ERROR_CACHE_TTL)
        if entry.display_name != "unknown" or entry.preferences or entry.prompt_summary:
            return self._cache_ttl
        return min(self._cache_ttl, self._empty_cache_ttl)

    @classmethod
    def _normalize_preferences(cls, preferences: Dict[str, Any]) -> Dict[str, Any]:
        normalized: Dict[str, Any] = {}
        for key, value in preferences.items():
            normalized[str(key)] = cls._normalize_preference_value(value)
        return normalized

    @classmethod
    def _normalize_preference_value(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): cls._normalize_preference_value(inner) for key, inner in value.items()}
        if isinstance(value, list):
            return [cls._normalize_preference_value(item) for item in value]
        if not isinstance(value, str):
            return value

        text = value.strip()
        if not text or text[0] not in {"[", "{"}:
            return value
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, TypeError, ValueError):
            return value
        return cls._normalize_preference_value(parsed)

    @classmethod
    def _derive_display_name(cls, preferences: Dict[str, Any]) -> str:
        preferred = cls._first_text(preferences.get(_ADDRESS_PREFERRED_KEY))
        if preferred:
            return preferred

        preferred = cls._first_text(preferences.get("communication.address.preferred"))
        if preferred:
            return preferred

        real_name = cls._first_text(preferences.get(_ADDRESS_REAL_NAME_KEY))
        if real_name:
            return real_name

        real_name = cls._first_text(preferences.get("identity.real_name"))
        if real_name:
            return real_name

        return ""

    @staticmethod
    def _first_text(value: Any) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (list, tuple)):
            for item in value:
                text = str(item or "").strip()
                if text:
                    return text
        if isinstance(value, dict):
            candidate = value.get("value")
            return str(candidate or "").strip()
        return ""


def _prompt_lines(projection: Any) -> list[str]:
    if projection is None:
        return []
    return [line for line in projection.prompt_summary if str(line).strip()]


def _log_prompt_projection_failure(
    *,
    user_id: str,
    stage: str,
    error: Exception,
    cached_kept: bool,
) -> None:
    logger.error(
        "User portrait prompt projection input failed",
        user_id=user_id,
        projection_kind="portrait",
        stage=stage,
        cached_kept=cached_kept,
        error_type=type(error).__name__,
    )
