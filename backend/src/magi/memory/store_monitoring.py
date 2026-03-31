"""Mixin: monitoring / statistics helpers for UnifiedMemoryStore."""

from __future__ import annotations

from typing import Any, Dict


class MonitoringMixin:
    """Extracted methods that expose store statistics and diagnostics."""

    async def get_statistics(self) -> Dict[str, Any]:
        """Return per-layer statistics."""
        stats: Dict[str, Any] = {}
        if self.l0 is not None:  # type: ignore[attr-defined]
            stats["l0"] = {"checkpoint_db_path": self.l0.checkpoint_db_path}  # type: ignore[attr-defined]
        if self.l1 is not None:  # type: ignore[attr-defined]
            l1_stats = self.l1.get_statistics() if hasattr(self.l1, "get_statistics") else {"db_path": self.l1.db_path}  # type: ignore[attr-defined]
            stats["l1"] = {
                **l1_stats,
                "event_count": await self.l1.count_events(),  # type: ignore[attr-defined]
            }
        if self.l2 is not None:  # type: ignore[attr-defined]
            stats["l2"] = {
                **self.l2.get_statistics(),  # type: ignore[attr-defined]
                "projection_backlog": await self.l2.get_projection_backlog_stats(),  # type: ignore[attr-defined]
            }
        if self.l2_pipeline is not None:  # type: ignore[attr-defined]
            stats["l2_pipeline"] = self.l2_pipeline.get_statistics()  # type: ignore[attr-defined]
        if self.l3 is not None:  # type: ignore[attr-defined]
            stats["l3"] = self.l3.get_statistics() if hasattr(self.l3, "get_statistics") else {"db_path": self.l3.db_path}  # type: ignore[attr-defined]
        if self.l4 is not None:  # type: ignore[attr-defined]
            stats["l4"] = self.l4.get_statistics()  # type: ignore[attr-defined]
        return stats

    def get_l2_pipeline_stats(self) -> Dict[str, Any]:
        """Expose current background L2 pipeline counters."""
        if self.l2_pipeline is None:  # type: ignore[attr-defined]
            return {
                "is_running": False,
                "extract_enqueued": 0,
                "extract_completed": 0,
                "extract_failed": 0,
                "extract_skipped": 0,
                "reconcile_enqueued": 0,
                "reconcile_completed": 0,
                "reconcile_failed": 0,
                "snapshot_enqueued": 0,
                "snapshot_completed": 0,
                "snapshot_failed": 0,
                "relations_written": 0,
                "assertions_written": 0,
                "extract_by_evidence_class": {},
                "skip_by_reason": {},
            }
        return self.l2_pipeline.get_statistics()  # type: ignore[attr-defined]

    async def get_l2_projection_backlog(self) -> Dict[str, int]:
        """Return durable L2 projection backlog counts."""
        if self.l2 is None:  # type: ignore[attr-defined]
            return {
                "pending": 0,
                "claimed": 0,
                "completed": 0,
                "failed": 0,
            }
        return await self.l2.get_projection_backlog_stats()  # type: ignore[attr-defined]
