"""Episode consolidation helpers for L2 entity maintenance."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from ...core.logger import get_logger

if TYPE_CHECKING:
    from .store import L2CognitionStore

logger = get_logger("magi.memory.l2.entity_maintenance")


class _EpisodeMaintenanceStatsProtocol(Protocol):
    episodes_promoted: int
    episodes_merged: int
    episodes_invalidated: int
    errors: list[str]


class _EpisodeMaintenanceHostProtocol(Protocol):
    _cognition_store: L2CognitionStore | None


class L2EntityEpisodeMaintenanceMixin:
    """Run offline episode consolidation from the entity maintenance schedule."""

    async def _consolidate_episodes(
        self,
        stats: _EpisodeMaintenanceStatsProtocol,
    ) -> None:
        host = self._episode_maintenance_host()
        cognition_store = host._cognition_store
        if cognition_store is None:
            return
        try:
            from .episode_formation import consolidate_episodes

            result = await consolidate_episodes(cognition_store)
            stats.episodes_promoted = result.promoted
            stats.episodes_merged = result.merged
            stats.episodes_invalidated = result.invalidated
        except Exception as exc:
            logger.warning("Episode consolidation failed: %s", exc)
            stats.errors.append(f"episode_consolidation: {exc}")

    def _episode_maintenance_host(self) -> _EpisodeMaintenanceHostProtocol:
        return self  # type: ignore[return-value]
