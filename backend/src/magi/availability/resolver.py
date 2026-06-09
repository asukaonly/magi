"""AvailabilityResolver: cached per-device probing of plugin requirements."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Callable

from magi.availability.checks import _current_platform_key
from magi.availability.contracts import AvailabilityReason, AvailabilityResult
from magi_plugin_sdk.contracts import (
    LocalRequirementAppInstalled,
    LocalRequirementExecutableInPath,
    LocalRequirementFileExists,
    PluginManifest,
    SuggestionDescriptor,
)

logger = logging.getLogger(__name__)

ManifestProvider = Callable[[str], PluginManifest | None]


@dataclass
class _CacheEntry:
    result: AvailabilityResult
    expires_at: datetime


# Map check_kind value → reason on failure
_KIND_TO_FAILURE_REASON = {
    "file_exists": AvailabilityReason.MISSING_FILE,
    "executable_in_path": AvailabilityReason.MISSING_EXECUTABLE,
    "app_installed": AvailabilityReason.APP_NOT_INSTALLED,
}


class AvailabilityResolver:
    """Answers `is this plugin runnable on this device?` with caching.

    Thread-safe (cache access guarded). Probes are synchronous and cheap.
    """

    def __init__(
        self,
        *,
        manifest_provider: ManifestProvider,
        ttl: timedelta = timedelta(minutes=5),
    ) -> None:
        self._manifest_provider = manifest_provider
        self._ttl = ttl
        self._cache: dict[str, _CacheEntry] = {}
        self._lock = Lock()

    def is_available(self, plugin_id: str) -> AvailabilityResult:
        now = datetime.now(timezone.utc)
        with self._lock:
            entry = self._cache.get(plugin_id)
            if entry is not None and entry.expires_at > now:
                return entry.result

        result = self._probe(plugin_id, now)

        with self._lock:
            self._cache[plugin_id] = _CacheEntry(
                result=result, expires_at=now + self._ttl
            )
        return result

    def list_available(self, *, plugin_ids: list[str]) -> list[str]:
        return [pid for pid in plugin_ids if self.is_available(pid).available]

    def evaluate_descriptor(
        self,
        descriptor: SuggestionDescriptor,
        *,
        plugin_id: str = "",
        now: datetime | None = None,
    ) -> AvailabilityResult:
        """Evaluate a descriptor's platform_support + local_requirements directly.

        Independent of install state — the descriptor may come from a registry
        entry for a plugin that is NOT installed on this device. Performs no
        manifest lookup and is NOT cached (callers that want caching go through
        :meth:`is_available`, which delegates here).

        The platform check and the AND-combined local requirements are the same
        core the installed-plugin path runs. ``plugin_id`` is echoed back on the
        result purely for labelling (registry-only descriptors may pass "").
        """
        return self._evaluate_descriptor(
            descriptor, plugin_id=plugin_id, now=now or datetime.now(timezone.utc)
        )

    def invalidate(self, plugin_id: str | None = None) -> None:
        with self._lock:
            if plugin_id is None:
                self._cache.clear()
            else:
                self._cache.pop(plugin_id, None)

    # --- internals ------------------------------------------------------

    def _probe(self, plugin_id: str, now: datetime) -> AvailabilityResult:
        manifest = self._manifest_provider(plugin_id)
        if manifest is None or manifest.suggestion_descriptor is None:
            return AvailabilityResult(
                plugin_id=plugin_id,
                available=False,
                reason=AvailabilityReason.NO_DESCRIPTOR,
                checked_at=now,
            )

        return self._evaluate_descriptor(
            manifest.suggestion_descriptor, plugin_id=plugin_id, now=now
        )

    def _evaluate_descriptor(
        self, descriptor: SuggestionDescriptor, *, plugin_id: str, now: datetime
    ) -> AvailabilityResult:
        """Core descriptor evaluation: platform check + AND-combined requirements.

        Shared by the installed-plugin path (:meth:`_probe`) and the
        registry/not-installed path (:meth:`evaluate_descriptor`).
        """
        current_platform = _current_platform_key()
        if current_platform not in descriptor.platform_support:
            return AvailabilityResult(
                plugin_id=plugin_id,
                available=False,
                reason=AvailabilityReason.UNSUPPORTED_PLATFORM,
                detail=f"platform {current_platform!r} not in {descriptor.platform_support}",
                checked_at=now,
            )

        for req in descriptor.local_requirements:
            try:
                ok, detail = self._dispatch(req)
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "availability check raised for plugin=%s kind=%s", plugin_id, req.check_kind
                )
                return AvailabilityResult(
                    plugin_id=plugin_id,
                    available=False,
                    reason=AvailabilityReason.CHECK_ERROR,
                    detail=str(exc),
                    checked_at=now,
                )
            if not ok:
                return AvailabilityResult(
                    plugin_id=plugin_id,
                    available=False,
                    reason=_KIND_TO_FAILURE_REASON.get(
                        req.check_kind, AvailabilityReason.CHECK_ERROR
                    ),
                    detail=detail,
                    checked_at=now,
                )

        return AvailabilityResult(
            plugin_id=plugin_id,
            available=True,
            reason=AvailabilityReason.AVAILABLE,
            checked_at=now,
        )

    @staticmethod
    def _dispatch(req) -> tuple[bool, str | None]:
        # Re-import the checks module at call time so unittest.mock.patch
        # targeting `magi.availability.checks.check_*` reliably intercepts.
        if isinstance(req, LocalRequirementFileExists):
            from magi.availability import checks as _c

            return _c.check_file_exists(req)
        if isinstance(req, LocalRequirementExecutableInPath):
            from magi.availability import checks as _c

            return _c.check_executable_in_path(req)
        if isinstance(req, LocalRequirementAppInstalled):
            from magi.availability import checks as _c

            return _c.check_app_installed(req)
        raise NotImplementedError(f"unsupported check kind: {type(req).__name__}")
