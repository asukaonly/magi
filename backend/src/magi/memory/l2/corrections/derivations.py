"""Durable rebuilding of correction-sensitive derived memory views."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import aiosqlite

from ....core.logger import get_logger
from ....core.sqlite import sqlite_connection_async
from ...derivation_revision import DerivationRevision, DerivationRevisionChangedError
from ....user_profile.portrait_projection_builder import UserPortraitProjectionBuilder
from ....user_profile.portrait_projection_repository import UserPortraitProjectionRepository
from ....user_profile.projection_builder import UserProfileProjectionBuilder
from ....user_profile.projection_repository import UserProfileProjectionRepository
from .repository import (
    DEFAULT_DERIVATION_MAX_ATTEMPTS,
    MemoryCorrectionRepository,
)

logger = get_logger(__name__)

DerivationHandler = Callable[[Mapping[str, Any]], Awaitable[None]]


class CorrectionDerivationRunner:
    """Drain correction follow-ups with stale-read protection and retries."""

    def __init__(
        self,
        *,
        db_path: str,
        l2_store: Any,
        handlers: Mapping[str, DerivationHandler] | None = None,
    ) -> None:
        self._db_path = db_path
        self._l2_store = l2_store
        self._repository = MemoryCorrectionRepository(db_path)
        self._handlers = dict(handlers or {})

    async def run_pending(
        self,
        *,
        limit: int = 50,
        recover_interrupted: bool = False,
        max_attempts: int = DEFAULT_DERIVATION_MAX_ATTEMPTS,
    ) -> dict[str, int]:
        """Run ready jobs without allowing a rebuild failure to escape."""
        if recover_interrupted:
            await self._repository.requeue_running_jobs()
        stats = {"completed": 0, "failed": 0, "superseded": 0}
        for _ in range(max(0, int(limit))):
            job = await self._repository.claim_next_derivation_job(
                max_attempts=max_attempts,
            )
            if job is None:
                break
            current_revision = await self._repository.current_subject_revision(
                str(job["target_key"])
            )
            if int(job["target_revision"]) != current_revision:
                await self._repository.complete_derivation_job(
                    str(job["job_id"]),
                    message=f"Superseded by revision {current_revision}",
                )
                stats["superseded"] += 1
                continue
            try:
                await self._run_job(job)
                latest_revision = await self._repository.current_subject_revision(
                    str(job["target_key"])
                )
                if latest_revision != current_revision:
                    await self._repository.complete_derivation_job(
                        str(job["job_id"]),
                        message=f"Superseded by revision {latest_revision}",
                    )
                    stats["superseded"] += 1
                    continue
                await self._repository.complete_derivation_job(str(job["job_id"]))
                stats["completed"] += 1
            except DerivationRevisionChangedError as exc:
                latest_revision = await self._repository.current_subject_revision(
                    str(job["target_key"])
                )
                await self._repository.complete_derivation_job(
                    str(job["job_id"]),
                    message=f"Superseded by revision {latest_revision}: {exc}",
                )
                stats["superseded"] += 1
            except Exception as exc:  # pragma: no cover - exercised through behavior tests
                await self._repository.fail_derivation_job(
                    str(job["job_id"]),
                    error=str(exc),
                    attempt_count=int(job["attempt_count"]),
                    max_attempts=max_attempts,
                )
                stats["failed"] += 1
                logger.warning(
                    "Memory correction derivation failed",
                    job_id=str(job["job_id"]),
                    job_kind=str(job["job_kind"]),
                    target_key=str(job["target_key"]),
                    error=str(exc),
                )
        return stats

    async def _run_job(self, job: Mapping[str, Any]) -> None:
        job_kind = str(job["job_kind"])
        handler = self._handlers.get(job_kind)
        if handler is not None:
            await handler(job)
            return
        if job_kind == "snapshot":
            await self._rebuild_snapshot(job)
            return
        if job_kind == "profile":
            await self._rebuild_profile(job)
            return
        if job_kind == "portrait":
            await self._rebuild_portrait(job)
            return
        if job_kind == "l3_insight":
            await self._rebuild_l3_insights(job)
            return
        raise RuntimeError(f"No derivation handler registered for {job_kind}")

    async def _rebuild_snapshot(self, job: Mapping[str, Any]) -> None:
        entity_id = str(job["target_key"])
        entity_type = await self._entity_type(entity_id)
        snapshot = await self._l2_store.refresh_entity_snapshot(
            entity_id=entity_id,
            entity_type=entity_type,
        )
        if snapshot is None:
            await self._delete_snapshot(
                entity_id,
                expected_revision=int(job["target_revision"]),
            )
            return
        assertions = await self._l2_store.list_current_assertions(
            entity_id=entity_id,
            context_scope=None,
            limit=500,
        )
        outgoing = await self._l2_store.list_current_relationships(
            subject_id=entity_id,
            context_scope=None,
            limit=500,
        )
        incoming = await self._l2_store.list_current_relationships(
            object_id=entity_id,
            context_scope=None,
            limit=500,
        )
        sources = [
            *(("assertion", str(item["assertion_id"])) for item in assertions),
            *(("edge", str(item["triple_id"])) for item in outgoing),
            *(("edge", str(item["triple_id"])) for item in incoming),
        ]
        await self._repository.replace_dependencies(
            artifact_kind="snapshot",
            artifact_id=str(snapshot["snapshot_id"]),
            subject_key=entity_id,
            source_revision=int(job["target_revision"]),
            sources=sources,
        )

    async def _rebuild_profile(self, job: Mapping[str, Any]) -> None:
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

    async def _rebuild_portrait(self, job: Mapping[str, Any]) -> None:
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
        sources = []
        for reference in stored.evidence_refs:
            if reference.startswith("assertion:"):
                sources.append(("assertion", reference.split(":", 1)[1]))
        await self._repository.replace_dependencies(
            artifact_kind="portrait",
            artifact_id=user_id,
            subject_key=entity_id,
            source_revision=int(job["target_revision"]),
            sources=sources,
        )

    async def _rebuild_l3_insights(self, job: Mapping[str, Any]) -> None:
        from ...l3.correction_derivation import L3CorrectionDerivationService

        await L3CorrectionDerivationService(
            db_path=self._db_path,
            l2_store=self._l2_store,
        ).rebuild_subject(
            str(job["target_key"]),
            expected_revision=int(job["target_revision"]),
        )

    async def _entity_type(self, entity_id: str) -> str:
        async with sqlite_connection_async(self._db_path) as db:
            async with db.execute(
                """
                SELECT entity_type FROM tom_trait_assertions WHERE entity_id = ?
                UNION ALL
                SELECT subject_type FROM knowledge_graph WHERE subject_id = ?
                UNION ALL
                SELECT object_type FROM knowledge_graph WHERE object_id = ?
                LIMIT 1
                """,
                (entity_id, entity_id, entity_id),
            ) as cursor:
                row = await cursor.fetchone()
        if row is not None and str(row[0]).strip():
            return str(row[0])
        return entity_id.split(":", 1)[0] if ":" in entity_id else "entity"

    async def _delete_snapshot(
        self,
        entity_id: str,
        *,
        expected_revision: int,
    ) -> None:
        revision = DerivationRevision(
            subject_key=entity_id,
            source_revision=expected_revision,
        )
        async with sqlite_connection_async(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                await revision.ensure_current_on_connection(db)
                async with db.execute(
                    """
                    SELECT snapshot_id FROM tom_snapshots
                    WHERE entity_id = ? AND source_revision <= ?
                    """,
                    (entity_id, expected_revision),
                ) as cursor:
                    rows = await cursor.fetchall()
                await db.execute(
                    """
                    DELETE FROM tom_snapshots
                    WHERE entity_id = ? AND source_revision <= ?
                    """,
                    (entity_id, expected_revision),
                )
                await db.executemany(
                    """
                    DELETE FROM memory_derivation_dependencies
                    WHERE artifact_kind = 'snapshot' AND artifact_id = ?
                    """,
                    [(str(row["snapshot_id"]),) for row in rows],
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise


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


__all__ = ["CorrectionDerivationRunner"]
