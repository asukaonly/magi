"""A decision belongs to an identity, not a repeated model suggestion."""

import pytest

from magi.core.sqlite import sqlite_connection_async
from magi.memory.l2.entities.catalog import L2EntityCatalog
from magi.memory.l2.entities.governance import EntityIdentityService
from magi.memory.l2.entities.governance_models import EntityChangeCommand, EntityChangeApplyRequest
from magi.memory.l2.entities.governance_read import EntityIdentityConflictError, query_rows


async def propose(service, entity_id, kind, event_id="event"):
    await service.catalog.record_mention(
        mention_text="Atlas",
        normalized_surface="atlas",
        entity_type=kind,
        evidence_event_ids=[event_id],
        evidence_text="Atlas",
        resolved_entity_id=entity_id,
        confidence=0.9,
    )


@pytest.fixture
async def service(tmp_path):
    catalog = L2EntityCatalog(db_path=str(tmp_path / "memory.db"), vector_enabled=False)
    await catalog.upsert_entity(entity_id="one", canonical_name="Atlas", entity_type="other")
    service = EntityIdentityService(catalog)
    await propose(service, "one", "software")
    await propose(service, "one", "technology")
    return service


@pytest.mark.asyncio
async def test_grouping_precedes_pagination_and_does_not_merge_namesakes(service):
    await service.catalog.upsert_entity(
        entity_id="two", canonical_name="Atlas", entity_type="other"
    )
    await propose(service, "two", "software")
    first = await service.list_review_groups(limit=1)
    second = await service.list_review_groups(limit=1, offset=1)
    assert first.total == second.total == 2
    assert len(first.items[0].proposals) == 2
    assert first.items[0].entity.entity_id != second.items[0].entity.entity_id


@pytest.mark.asyncio
async def test_keep_rejects_all_choices_and_replay_does_not_reopen(service):
    group = (await service.list_review_groups()).items[0]
    result = await service.keep_classification("one", expected_fingerprint=group.fingerprint)
    assert result.rejected_count == 2
    await propose(service, "one", "software", "new-event")
    assert (await service.list_review_groups()).total == 0
    assert (await service.catalog.list_entities())[0]["entity_type"] == "other"


@pytest.mark.asyncio
async def test_new_evidence_invalidates_keep_entire_group(service):
    group = (await service.list_review_groups()).items[0]
    await propose(service, "one", "software", "new-event")
    with pytest.raises(EntityIdentityConflictError):
        await service.keep_classification("one", expected_fingerprint=group.fingerprint)
    assert (await service.list_reviews()).total == 2


@pytest.mark.asyncio
async def test_accepting_one_choice_closes_competing_proposals(service):
    proposal = (await service.list_reviews()).items[0]
    preview = await service.preview(
        EntityChangeCommand(
            kind="type_correction",
            entity_id="one",
            new_type=proposal.proposed_type,
            review_id=proposal.review_id,
        )
    )
    await service.apply(
        EntityChangeApplyRequest(
            command=preview.command, expected_fingerprint=preview.fingerprint, request_id="accept"
        ),
        actor_id="user:self",
    )
    assert (await service.list_reviews()).total == 0
    async with sqlite_connection_async(service.db_path) as db:
        assert {
            row["status"]
            for row in await query_rows(db, "SELECT status FROM entity_identity_reviews")
        } == {"applied", "rejected"}
