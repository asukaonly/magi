"""Shared invalidation and rebuild workflow for user-forgotten memory."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Protocol

import aiosqlite

from ....core.logger import get_logger
from ..corrections.derivations import CorrectionDerivationRunner
from ..corrections.forget_governance import ForgottenClaim
from ..corrections.repository import MemoryCorrectionRepository

logger = get_logger(__name__)


class ForgetDerivationHost(Protocol):
    db_path: str


async def invalidate_forgotten_derivations(
    db: aiosqlite.Connection,
    *,
    repository: MemoryCorrectionRepository,
    forgotten_assertions: Mapping[str, ForgottenClaim],
    forgotten_edges: Mapping[str, ForgottenClaim],
    now: float,
    explicit_subject_keys: tuple[str, ...] = (),
) -> dict[str, int]:
    """Hide every derived view that could still expose forgotten content."""
    subject_keys = {
        subject_key
        for claim in (*forgotten_assertions.values(), *forgotten_edges.values())
        for subject_key in claim.subject_keys
        if subject_key
    }
    subject_keys.update(
        str(subject_key).strip()
        for subject_key in explicit_subject_keys
        if str(subject_key).strip()
    )
    assertion_l3_subjects = await repository.invalidate_l3_insights_on_connection(
        db,
        source_kind="assertion",
        source_ids=forgotten_assertions,
        subject_keys=subject_keys,
        include_current_subjects=True,
        updated_at=now,
    )
    edge_l3_subjects = await repository.invalidate_l3_insights_on_connection(
        db,
        source_kind="edge",
        source_ids=forgotten_edges,
        subject_keys=subject_keys,
        include_current_subjects=True,
        updated_at=now,
    )
    subject_keys.update(assertion_l3_subjects)
    subject_keys.update(edge_l3_subjects)
    await _purge_forgotten_snapshot_baselines(
        db,
        subject_keys=subject_keys,
    )
    revisions: dict[str, int] = {}
    for subject_key in sorted(subject_keys):
        revisions[subject_key] = await repository.bump_subject_revision(
            db,
            subject_key=subject_key,
            updated_at=now,
        )
    return revisions


async def _purge_forgotten_snapshot_baselines(
    db: aiosqlite.Connection,
    *,
    subject_keys: set[str],
) -> None:
    """Remove snapshot history that may still contain forgotten material."""

    if not subject_keys:
        return
    subject_json = json.dumps(
        sorted(subject_keys),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    await db.execute(
        """
        DELETE FROM memory_derivation_dependencies
        WHERE artifact_kind = 'snapshot'
          AND artifact_id IN (
              SELECT snapshot_id
              FROM tom_snapshots
              WHERE entity_id IN (
                  SELECT CAST(value AS TEXT) FROM json_each(?)
              )
          )
        """,
        (subject_json,),
    )
    await db.execute(
        """
        DELETE FROM tom_snapshots
        WHERE entity_id IN (
            SELECT CAST(value AS TEXT) FROM json_each(?)
        )
        """,
        (subject_json,),
    )


async def rebuild_forgotten_subject_views(
    *,
    host: ForgetDerivationHost,
    revisions: Mapping[str, int],
) -> None:
    """Restore unaffected projections while keeping deletion fail-closed."""
    runner = CorrectionDerivationRunner(
        db_path=host.db_path,
        l2_store=host,
    )
    for subject_key, revision in revisions.items():
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                await runner.rebuild_subject_views(
                    subject_key=subject_key,
                    target_revision=revision,
                )
                last_error = None
                break
            except Exception as exc:  # noqa: PERF203
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(0.05 * (2**attempt))
        if last_error is not None:
            logger.warning(
                "Forgotten memory views remained hidden after rebuild retries",
                subject_key=subject_key,
                revision=revision,
                error=str(last_error),
            )


__all__ = [
    "ForgetDerivationHost",
    "invalidate_forgotten_derivations",
    "rebuild_forgotten_subject_views",
]
