"""One review decision per identity, independent of proposal count or label."""

from __future__ import annotations

import aiosqlite

from .governance_models import EntityTypeReview, EntityTypeReviewGroup, IdentityEntity
from .governance_read import (
    active_type_review,
    EntityIdentityNotFoundError,
    fingerprint,
    query_rows,
)


async def review_groups(db: aiosqlite.Connection) -> list[EntityTypeReviewGroup]:
    """Group active evidence-backed proposals while retaining distinct identities."""
    rows = await query_rows(
        db,
        "SELECT review_id FROM entity_identity_reviews WHERE status = 'pending' ORDER BY created_at, review_id",
    )
    grouped: dict[str, list[EntityTypeReview]] = {}
    for row in rows:
        try:
            review = await active_type_review(db, str(row["review_id"]))
        except EntityIdentityNotFoundError:
            continue
        proposal = EntityTypeReview(
            review_id=review["review_id"],
            entity=IdentityEntity.model_validate(review["entity"]),
            proposed_type=review["proposed_type"],
            evidence_event_ids=review["evidence_event_ids"],
            version=review["version"],
        )
        grouped.setdefault(proposal.entity.entity_id, []).append(proposal)
    groups = []
    for proposals in grouped.values():
        token = fingerprint([item.model_dump() for item in proposals])
        groups.append(
            EntityTypeReviewGroup(
                entity=proposals[0].entity,
                proposals=proposals,
                fingerprint=token,
            )
        )
    return groups
