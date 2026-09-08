"""User-owned entity classification and merge governance."""

from __future__ import annotations

import time
import uuid

from ....core.sqlite import sqlite_connection_async
from ....core.logger import get_logger
from ..corrections.cache_signals import mark_all_subjects_changed
from .catalog import L2EntityCatalog
from .governance_models import (
    EntityChangeApplyRequest,
    EntityChangeCommand,
    EntityChangePreview,
    EntityChangeResult,
    EntityIdentityAudit,
    EntityIdentityAuditGroup,
    EntityReviewRejectResult,
    EntityTypeReview,
    EntityTypeReviewList,
    IdentityEntity,
)
from .governance_read import (
    EntityIdentityConflictError,
    EntityIdentityNotFoundError,
    active_type_review,
    fingerprint,
    identity_preview,
    query_rows,
)
from .governance_write import apply_identity_change, enqueue_identity_derivations


class EntityIdentityService:
    def __init__(self, catalog: L2EntityCatalog) -> None:
        self.catalog = catalog
        self.db_path = catalog.db_path

    async def preview(self, command: EntityChangeCommand) -> EntityChangePreview:
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN")
            preview, _ = await identity_preview(db, command)
            return preview

    async def apply(
        self, request: EntityChangeApplyRequest, *, actor_id: str
    ) -> EntityChangeResult:
        request_hash = fingerprint({"actor_id": actor_id, **request.model_dump()})
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            prior = await query_rows(
                db,
                "SELECT * FROM entity_identity_operations WHERE request_id = ?",
                (request.request_id,),
            )
            if prior:
                if prior[0]["request_fingerprint"] != request_hash:
                    raise EntityIdentityConflictError(
                        "Request ID was already used for another change"
                    )
                prior_result: EntityChangeResult = EntityChangeResult.model_validate_json(
                    prior[0]["result_json"]
                )
                return prior_result
            preview, state = await identity_preview(db, request.command)
            if preview.fingerprint != request.expected_fingerprint:
                raise EntityIdentityConflictError(
                    "Entity data changed after preview; refresh before applying"
                )
            operation_id = f"identity_{uuid.uuid4().hex}"
            now = time.time()
            command = request.command
            result = EntityChangeResult(
                operation_id=operation_id,
                kind=command.kind,
                entity_id=command.target_entity_id or command.entity_id,
                current_type=command.new_type
                or (preview.target.entity_type if preview.target else preview.entity.entity_type),
                impact=preview.impact,
            )
            await db.execute(
                """INSERT INTO entity_identity_operations(
                operation_id, request_id, request_fingerprint, operation_kind, source_entity_id,
                target_entity_id, previous_type, current_type, actor_id, result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    operation_id,
                    request.request_id,
                    request_hash,
                    command.kind,
                    command.entity_id,
                    result.entity_id,
                    preview.entity.entity_type,
                    result.current_type,
                    actor_id,
                    result.model_dump_json(),
                    now,
                ),
            )
            invalidated = await apply_identity_change(
                db,
                db_path=self.db_path,
                preview=preview,
                state=state,
                operation_id=operation_id,
                now=now,
            )
            await enqueue_identity_derivations(
                db, db_path=self.db_path, state=state, operation_id=operation_id, now=now
            )
            await db.commit()
        mark_all_subjects_changed(self.db_path)
        # Retrieval filters pending vectors; physical cleanup is safe to retry independently.
        try:
            await self._invalidate_vectors(request, invalidated)
        except Exception as exc:
            get_logger(__name__).warning(
                "Entity identity committed; vector cleanup will be retried by maintenance",
                operation_id=result.operation_id,
                error=str(exc),
            )
        return result

    async def _invalidate_vectors(
        self, request: EntityChangeApplyRequest, invalidated: set[str]
    ) -> None:
        if self.catalog.edge_vector_index is not None:
            for triple_id in invalidated:
                await self.catalog.edge_vector_index.delete_entity(entity_id=triple_id)
        if self.catalog._vector_index is not None:
            await self.catalog._vector_index.delete_entity(entity_id=request.command.entity_id)
            if request.command.target_entity_id:
                await self.catalog._vector_index.delete_entity(
                    entity_id=request.command.target_entity_id
                )

    async def list_reviews(self, *, limit: int = 100, offset: int = 0) -> EntityTypeReviewList:
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN")
            rows = await query_rows(
                db,
                "SELECT review_id FROM entity_identity_reviews WHERE status = 'pending' ORDER BY created_at, review_id",
            )
            items: list[EntityTypeReview] = []
            for row in rows:
                try:
                    review = await active_type_review(db, str(row["review_id"]))
                except EntityIdentityNotFoundError:
                    continue
                items.append(
                    EntityTypeReview(
                        review_id=str(review["review_id"]),
                        entity=IdentityEntity.model_validate(review["entity"]),
                        proposed_type=str(review["proposed_type"]),
                        evidence_event_ids=review["evidence_event_ids"],
                        version=int(review["version"]),
                    )
                )
            return EntityTypeReviewList(items=items[offset : offset + limit], total=len(items))

    async def reject_review(
        self, review_id: str, *, expected_version: int
    ) -> EntityReviewRejectResult:
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            review = await active_type_review(db, review_id)
            if review["version"] != expected_version:
                raise EntityIdentityConflictError("Entity review changed; refresh before rejecting")
            await db.execute(
                "UPDATE entity_identity_reviews SET status = 'rejected', version = version + 1, updated_at = ? WHERE review_id = ?",
                (time.time(), review_id),
            )
            await db.commit()
        return EntityReviewRejectResult(review_id=review_id)

    async def audit(self, *, limit: int = 50, offset: int = 0) -> EntityIdentityAudit:
        """List historical homonyms for review without declaring them duplicates."""
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN")
            names = await query_rows(
                db,
                "SELECT LOWER(TRIM(canonical_name)) AS name FROM entity_catalog GROUP BY LOWER(TRIM(canonical_name)) HAVING COUNT(*) > 1 ORDER BY name",
            )
            groups: list[EntityIdentityAuditGroup] = []
            for name in names[offset : offset + limit]:
                entities = await query_rows(
                    db,
                    "SELECT entity_id, canonical_name, entity_type FROM entity_catalog WHERE LOWER(TRIM(canonical_name)) = ? ORDER BY entity_id",
                    (name["name"],),
                )
                groups.append(
                    EntityIdentityAuditGroup(
                        name=str(name["name"]),
                        entities=[IdentityEntity.model_validate(item) for item in entities],
                    )
                )
            return EntityIdentityAudit(groups=groups, total=len(names))
