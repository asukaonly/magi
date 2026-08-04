"""Offline-style L2 entity catalog and knowledge-graph maintenance."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...store import L2CognitionStore

from .....core.logger import get_logger
from ....embedding.embedding_pipeline import MemoryEmbeddingPipeline as MemoryEmbeddingPipeline
from ....embedding.sqlite_vec_index import SqliteVecIndex
from ...claims.reprojection import (
    list_unrouted_claim_backlog,
    reproject_stale_claim_routes,
)
from .assertions import L2EntityAssertionMaintenanceMixin
from .catalog import (
    L2EntityCatalogMaintenanceMixin,
    _canonical_entity_id,
)
from .edges import L2EntityEdgeMaintenanceMixin
from .embeddings import L2EntityEmbeddingMaintenanceMixin
from .episodes import L2EntityEpisodeMaintenanceMixin
from .predicates import L2EntityPredicateMaintenanceMixin
from ...ontology import get_predicate_synonym_group as get_predicate_synonym_group
from ...semantic_routing import ROUTE_CONTRACT_VERSION

logger = get_logger(__name__)

SCHEDULE_ID_L2_MAINTENANCE = "memory-l2-maintenance:global"
TARGET_KEY_L2_MAINTENANCE = "memory_l2_maintenance"

__all__ = [
    "L2EntityMaintenance",
    "L2EntityMaintenanceStats",
    "L2MaintenanceLifecycle",
    "_canonical_entity_id",
    "get_predicate_synonym_group",
]


@dataclass(frozen=True)
class L2MaintenanceLifecycle:
    """Tunable lifecycle thresholds for L2 maintenance.

    Defaults are the daemon's canonical values; the runtime schedule builds this
    from ``agent.memory.l2.lifecycle``. Kept config-agnostic so the daemon stays
    decoupled from pydantic settings and remains easy to test in isolation.
    """

    fast_decay_ttl_seconds: float = 4 * 3600
    session_decay_ttl_seconds: float = 24 * 3600
    archive_confidence_threshold: float = 0.3
    archive_staleness_seconds: float = 90 * 86400
    archive_single_observation_staleness_seconds: float = 180 * 86400
    purge_terminal_edge_staleness_seconds: float = 365 * 86400
    reconcile_stale_threshold_seconds: float = 3600
    reconcile_batch_size: int = 100
    reconcile_max_total: int = 500


@dataclass
class L2EntityMaintenanceStats:
    """Counters from one maintenance run."""

    ghost_edges_rewritten: int = 0
    ghost_rows_merged: int = 0
    ghost_skipped_no_target: int = 0
    tom_entity_refs_rewritten: int = 0
    fragment_entities_merged: int = 0
    fragment_groups_processed: int = 0
    orphans_pruned: int = 0
    expired_future_intents: int = 0
    expired_assertions: int = 0
    stale_snapshots_cleaned: int = 0
    entities_reconciled: int = 0
    snapshots_refreshed: int = 0
    open_predicates_consolidated: int = 0
    edges_archived: int = 0
    edges_purged: int = 0
    edge_embeddings_cleaned: int = 0
    episodes_promoted: int = 0
    episodes_merged: int = 0
    episodes_invalidated: int = 0
    unrouted_claim_count: int = 0
    unrouted_claim_backlog: list[dict[str, Any]] = field(default_factory=list)
    claim_route_candidates_selected: int = 0
    claim_route_outcomes_appended: int = 0
    claim_route_outcomes_already_present: int = 0
    claim_route_claims_no_longer_active: int = 0
    claim_route_target_outcomes_invalidated: int = 0
    claim_route_target_outcomes_revalidated: int = 0
    claim_route_targets_archived: int = 0
    claim_route_shared_targets_preserved: int = 0
    claim_route_authority_targets_preserved: int = 0
    claim_route_reprojection_failed: int = 0
    promoted_episode_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _L2MaintenanceRunPlan:
    min_mentions_to_keep: int
    resolve_ghosts: bool
    merge_fragments: bool
    prune_orphans: bool
    expire_future_intents: bool
    expire_decayed_assertions: bool
    clean_stale_snapshots: bool
    reconcile_stale: bool
    consolidate_open_predicates: bool
    archive_stale_edges: bool
    purge_terminal_edges: bool
    consolidate_episodes: bool


class L2EntityMaintenance(
    L2EntityCatalogMaintenanceMixin,
    L2EntityAssertionMaintenanceMixin,
    L2EntityEmbeddingMaintenanceMixin,
    L2EntityEdgeMaintenanceMixin,
    L2EntityPredicateMaintenanceMixin,
    L2EntityEpisodeMaintenanceMixin,
):
    """Best-effort cleanup: ghost graph refs, same-name type merges, low-mention orphans."""

    # Lifecycle thresholds are injected via L2MaintenanceLifecycle (config-driven
    # from agent.memory.l2.lifecycle); the mixins read them through the host.
    RECONCILE_STALE_THRESHOLD: float
    RECONCILE_BATCH_SIZE: int
    RECONCILE_MAX_TOTAL: int
    ARCHIVE_CONFIDENCE_THRESHOLD: float
    ARCHIVE_STALENESS_SECONDS: float
    ARCHIVE_SINGLE_OBS_STALENESS: float
    PURGE_TERMINAL_EDGE_STALENESS: float
    FAST_DECAY_TTL: float
    SESSION_DECAY_TTL: float

    def __init__(
        self,
        *,
        db_path: str,
        embedding_service: Any | None = None,
        edge_vector_index: SqliteVecIndex | None = None,
        cognition_store: L2CognitionStore | None = None,
        lifecycle: L2MaintenanceLifecycle | None = None,
    ) -> None:
        self._db_path = db_path
        self._embedding_service = embedding_service
        self._edge_vector_index = edge_vector_index
        self._cognition_store = cognition_store
        self._run_lock = asyncio.Lock()

        lc = lifecycle or L2MaintenanceLifecycle()
        self._lifecycle = lc
        self.RECONCILE_STALE_THRESHOLD = lc.reconcile_stale_threshold_seconds
        self.RECONCILE_BATCH_SIZE = lc.reconcile_batch_size
        self.RECONCILE_MAX_TOTAL = lc.reconcile_max_total
        self.ARCHIVE_CONFIDENCE_THRESHOLD = lc.archive_confidence_threshold
        self.ARCHIVE_STALENESS_SECONDS = lc.archive_staleness_seconds
        self.ARCHIVE_SINGLE_OBS_STALENESS = lc.archive_single_observation_staleness_seconds
        self.PURGE_TERMINAL_EDGE_STALENESS = lc.purge_terminal_edge_staleness_seconds
        self.FAST_DECAY_TTL = lc.fast_decay_ttl_seconds
        self.SESSION_DECAY_TTL = lc.session_decay_ttl_seconds

    async def run(
        self,
        *,
        min_mentions_to_keep: int = 2,
        resolve_ghosts: bool = True,
        merge_fragments: bool = True,
        prune_orphans: bool = True,
        expire_future_intents: bool = True,
        expire_decayed_assertions: bool = True,
        clean_stale_snapshots: bool = True,
        reconcile_stale: bool = True,
        consolidate_open_predicates: bool = True,
        archive_stale_edges: bool = True,
        purge_terminal_edges: bool = True,
        consolidate_episodes: bool = False,
    ) -> L2EntityMaintenanceStats:
        if self._run_lock.locked():
            logger.info("L2 maintenance already running, skipping")
            return L2EntityMaintenanceStats()
        async with self._run_lock:
            return await self._run_locked(
                min_mentions_to_keep=min_mentions_to_keep,
                resolve_ghosts=resolve_ghosts,
                merge_fragments=merge_fragments,
                prune_orphans=prune_orphans,
                expire_future_intents=expire_future_intents,
                expire_decayed_assertions=expire_decayed_assertions,
                clean_stale_snapshots=clean_stale_snapshots,
                reconcile_stale=reconcile_stale,
                consolidate_open_predicates=consolidate_open_predicates,
                archive_stale_edges=archive_stale_edges,
                purge_terminal_edges=purge_terminal_edges,
                consolidate_episodes=consolidate_episodes,
            )

    async def _run_locked(
        self,
        *,
        min_mentions_to_keep: int,
        resolve_ghosts: bool,
        merge_fragments: bool,
        prune_orphans: bool,
        expire_future_intents: bool,
        expire_decayed_assertions: bool,
        clean_stale_snapshots: bool,
        reconcile_stale: bool,
        consolidate_open_predicates: bool,
        archive_stale_edges: bool,
        purge_terminal_edges: bool,
        consolidate_episodes: bool,
    ) -> L2EntityMaintenanceStats:
        plan = _L2MaintenanceRunPlan(
            min_mentions_to_keep=min_mentions_to_keep,
            resolve_ghosts=resolve_ghosts,
            merge_fragments=merge_fragments,
            prune_orphans=prune_orphans,
            expire_future_intents=expire_future_intents,
            expire_decayed_assertions=expire_decayed_assertions,
            clean_stale_snapshots=clean_stale_snapshots,
            reconcile_stale=reconcile_stale,
            consolidate_open_predicates=consolidate_open_predicates,
            archive_stale_edges=archive_stale_edges,
            purge_terminal_edges=purge_terminal_edges,
            consolidate_episodes=consolidate_episodes,
        )
        stats = L2EntityMaintenanceStats()
        await self._run_entity_cleanup_steps(plan, stats)
        await self._run_claim_route_steps(stats)
        await self._run_assertion_decay_steps(plan, stats)
        await self._run_snapshot_reconciliation_steps(plan, stats)
        await self._run_edge_cleanup_steps(plan, stats)
        await self._run_episode_cleanup_steps(plan, stats)
        _log_maintenance_stats(stats)
        return stats

    async def _run_claim_route_steps(self, stats: L2EntityMaintenanceStats) -> None:
        try:
            backlog = await list_unrouted_claim_backlog(self._db_path)
        except Exception as exc:
            stats.errors.append(f"claim_route_backlog:{exc}")
            logger.warning("L2 unrouted Claim backlog query failed", error=str(exc))
            return

        stats.unrouted_claim_backlog = [asdict(group) for group in backlog]
        stats.unrouted_claim_count = sum(group.claim_count for group in backlog)
        if backlog:
            logger.info(
                "L2 unrouted Claim backlog",
                total_claims=stats.unrouted_claim_count,
                route_contract_version=ROUTE_CONTRACT_VERSION,
                groups=stats.unrouted_claim_backlog,
            )

        if self._cognition_store is None:
            return
        try:
            reprojection = await reproject_stale_claim_routes(self._cognition_store)
        except Exception as exc:
            stats.errors.append(f"claim_route_reprojection:{exc}")
            logger.warning("L2 Claim route reprojection failed", error=str(exc))
            return

        stats.claim_route_candidates_selected = reprojection.candidates_selected
        stats.claim_route_outcomes_appended = reprojection.outcomes_appended
        stats.claim_route_outcomes_already_present = reprojection.outcomes_already_present
        stats.claim_route_claims_no_longer_active = reprojection.claims_no_longer_active
        stats.claim_route_target_outcomes_invalidated = reprojection.target_outcomes_invalidated
        stats.claim_route_target_outcomes_revalidated = reprojection.target_outcomes_revalidated
        stats.claim_route_targets_archived = reprojection.targets_archived
        stats.claim_route_shared_targets_preserved = reprojection.shared_targets_preserved
        stats.claim_route_authority_targets_preserved = reprojection.authority_targets_preserved
        stats.claim_route_reprojection_failed = reprojection.failed

    async def _run_entity_cleanup_steps(
        self, plan: _L2MaintenanceRunPlan, stats: L2EntityMaintenanceStats
    ) -> None:
        if plan.resolve_ghosts:
            await self._resolve_ghost_graph_refs(stats)
        if plan.merge_fragments:
            await self._merge_fragmented_entities(stats)
        if plan.prune_orphans:
            await self._prune_orphan_low_mention_entities(
                stats, min_mentions=plan.min_mentions_to_keep
            )

    async def _run_assertion_decay_steps(
        self, plan: _L2MaintenanceRunPlan, stats: L2EntityMaintenanceStats
    ) -> None:
        if plan.expire_future_intents:
            await self._expire_stale_future_intents(stats)
        if plan.expire_decayed_assertions:
            await self._expire_decayed_assertions(stats)

    async def _run_snapshot_reconciliation_steps(
        self, plan: _L2MaintenanceRunPlan, stats: L2EntityMaintenanceStats
    ) -> None:
        if plan.clean_stale_snapshots:
            await self._clean_stale_snapshots(stats)
        if plan.reconcile_stale:
            await self._reconcile_stale_entities(stats)
        if plan.consolidate_open_predicates:
            await self._consolidate_open_predicates(stats)

    async def _run_edge_cleanup_steps(
        self, plan: _L2MaintenanceRunPlan, stats: L2EntityMaintenanceStats
    ) -> None:
        if plan.archive_stale_edges:
            await self._archive_stale_edges(stats)
        if plan.purge_terminal_edges:
            await self._purge_terminal_edges(stats)

    async def _run_episode_cleanup_steps(
        self, plan: _L2MaintenanceRunPlan, stats: L2EntityMaintenanceStats
    ) -> None:
        if plan.consolidate_episodes:
            await self._consolidate_episodes(stats)


def _log_maintenance_stats(stats: L2EntityMaintenanceStats) -> None:
    if not _maintenance_has_changes(stats):
        return
    logger.info(
        "L2 entity maintenance completed",
        ghost_edges_rewritten=stats.ghost_edges_rewritten,
        ghost_rows_merged=stats.ghost_rows_merged,
        ghost_skipped=stats.ghost_skipped_no_target,
        tom_entity_refs_rewritten=stats.tom_entity_refs_rewritten,
        fragment_entities_merged=stats.fragment_entities_merged,
        fragment_groups=stats.fragment_groups_processed,
        orphans_pruned=stats.orphans_pruned,
        expired_future_intents=stats.expired_future_intents,
        expired_assertions=stats.expired_assertions,
        stale_snapshots_cleaned=stats.stale_snapshots_cleaned,
        entities_reconciled=stats.entities_reconciled,
        snapshots_refreshed=stats.snapshots_refreshed,
        open_predicates_consolidated=stats.open_predicates_consolidated,
        edges_archived=stats.edges_archived,
        edges_purged=stats.edges_purged,
        edge_embeddings_cleaned=stats.edge_embeddings_cleaned,
        episodes_promoted=stats.episodes_promoted,
        episodes_merged=stats.episodes_merged,
        episodes_invalidated=stats.episodes_invalidated,
        unrouted_claim_count=stats.unrouted_claim_count,
        unrouted_claim_backlog=stats.unrouted_claim_backlog,
        claim_route_candidates_selected=stats.claim_route_candidates_selected,
        claim_route_outcomes_appended=stats.claim_route_outcomes_appended,
        claim_route_outcomes_already_present=stats.claim_route_outcomes_already_present,
        claim_route_claims_no_longer_active=stats.claim_route_claims_no_longer_active,
        claim_route_target_outcomes_invalidated=(stats.claim_route_target_outcomes_invalidated),
        claim_route_target_outcomes_revalidated=(stats.claim_route_target_outcomes_revalidated),
        claim_route_targets_archived=stats.claim_route_targets_archived,
        claim_route_shared_targets_preserved=(stats.claim_route_shared_targets_preserved),
        claim_route_authority_targets_preserved=(stats.claim_route_authority_targets_preserved),
        claim_route_reprojection_failed=stats.claim_route_reprojection_failed,
    )


def _maintenance_has_changes(stats: L2EntityMaintenanceStats) -> bool:
    return any(
        (
            stats.ghost_edges_rewritten,
            stats.ghost_rows_merged,
            stats.tom_entity_refs_rewritten,
            stats.fragment_entities_merged,
            stats.orphans_pruned,
            stats.expired_future_intents,
            stats.expired_assertions,
            stats.stale_snapshots_cleaned,
            stats.entities_reconciled,
            stats.snapshots_refreshed,
            stats.open_predicates_consolidated,
            stats.edges_archived,
            stats.edges_purged,
            stats.edge_embeddings_cleaned,
            stats.episodes_promoted,
            stats.episodes_merged,
            stats.episodes_invalidated,
            stats.unrouted_claim_count,
            stats.claim_route_outcomes_appended,
            stats.claim_route_claims_no_longer_active,
            stats.claim_route_target_outcomes_invalidated,
            stats.claim_route_target_outcomes_revalidated,
            stats.claim_route_targets_archived,
            stats.claim_route_shared_targets_preserved,
            stats.claim_route_authority_targets_preserved,
            stats.claim_route_reprojection_failed,
        )
    )
