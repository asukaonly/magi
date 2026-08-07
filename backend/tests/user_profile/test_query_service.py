from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from magi.user_profile.models import UserProfileProjection
from magi.user_profile.query_service import UserProfileQueryService


@pytest.mark.asyncio
async def test_get_current_profile_rebuilds_projection_from_l2():
    repository = AsyncMock()
    repository.get.return_value = None
    repository.upsert.side_effect = lambda projection: projection
    builder = AsyncMock()
    builder.build.return_value = UserProfileProjection(
        user_id="local_user",
        entity_id="user:local_user",
        display_name="子涵",
        preferred_form_of_address="子涵",
    )
    service = UserProfileQueryService(repository=repository, builder=builder)

    projection = await service.get_current_profile("local_user")

    builder.build.assert_awaited_once_with("local_user")
    repository.get.assert_awaited_once_with("local_user")
    repository.upsert.assert_awaited_once()
    assert projection.preferred_form_of_address == "子涵"


@pytest.mark.asyncio
async def test_get_current_profile_returns_fresh_cached_projection():
    cached = UserProfileProjection(
        user_id="local_user",
        entity_id="user:local_user",
        input_assertion_highwater=10.0,
    )
    repository = AsyncMock()
    repository.get.return_value = cached
    l2 = AsyncMock()
    l2.list_current_assertions.return_value = [
        {
            "trait_family": "identity_profile",
            "validation_state": "stable",
            "updated_at": 10.0,
        }
    ]
    l2.current_subject_revision.return_value = 0
    l2.current_clear_generation.return_value = 0
    builder = AsyncMock()
    builder.l2_store = l2
    service = UserProfileQueryService(repository=repository, builder=builder)

    projection = await service.get_current_profile("local_user")

    assert projection is cached
    builder.build.assert_not_awaited()
    repository.upsert.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_current_profile_rebuilds_when_assertion_highwater_changes():
    cached = UserProfileProjection(
        user_id="local_user",
        entity_id="user:local_user",
        input_assertion_highwater=10.0,
    )
    rebuilt = cached.model_copy(update={"input_assertion_highwater": 20.0})
    repository = AsyncMock()
    repository.get.return_value = cached
    repository.upsert.side_effect = lambda projection: projection
    l2 = AsyncMock()
    l2.list_current_assertions.return_value = [
        {
            "trait_family": "identity_profile",
            "validation_state": "stable",
            "updated_at": 20.0,
        }
    ]
    l2.current_subject_revision.return_value = 0
    l2.current_clear_generation.return_value = 0
    builder = AsyncMock()
    builder.l2_store = l2
    builder.build.return_value = rebuilt
    service = UserProfileQueryService(repository=repository, builder=builder)

    projection = await service.get_current_profile("local_user")

    assert projection.input_assertion_highwater == 20.0
    builder.build.assert_awaited_once_with("local_user")
    repository.upsert.assert_awaited_once_with(rebuilt)


@pytest.mark.asyncio
async def test_get_current_profile_rebuilds_when_selected_assertion_disappears():
    cached = UserProfileProjection(
        user_id="local_user",
        entity_id="user:local_user",
        field_sources={"real_name": {"assertion_id": "assert-old"}},
    )
    rebuilt = UserProfileProjection(user_id="local_user", entity_id="user:local_user")
    repository = AsyncMock()
    repository.get.return_value = cached
    repository.upsert.side_effect = lambda projection: projection
    l2 = AsyncMock()
    l2.list_current_assertions.return_value = []
    l2.current_subject_revision.return_value = 0
    l2.current_clear_generation.return_value = 0
    builder = AsyncMock()
    builder.l2_store = l2
    builder.build.return_value = rebuilt
    service = UserProfileQueryService(repository=repository, builder=builder)

    projection = await service.get_current_profile("local_user")

    assert projection is rebuilt
    builder.build.assert_awaited_once_with("local_user")


@pytest.mark.asyncio
async def test_get_current_profile_keeps_cache_when_freshness_read_fails():
    cached = UserProfileProjection(user_id="local_user", entity_id="user:local_user")
    repository = AsyncMock()
    repository.get.return_value = cached
    l2 = AsyncMock()
    l2.list_current_assertions.side_effect = RuntimeError("database unavailable")
    builder = AsyncMock()
    builder.l2_store = l2
    service = UserProfileQueryService(repository=repository, builder=builder)

    projection = await service.get_current_profile("local_user")

    assert projection is cached
    builder.build.assert_not_awaited()
    repository.upsert.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_current_profile_raises_when_no_cache_and_rebuild_fails():
    repository = AsyncMock()
    repository.get.return_value = None
    builder = AsyncMock()
    builder.build.side_effect = RuntimeError("database unavailable")
    service = UserProfileQueryService(repository=repository, builder=builder)

    with pytest.raises(RuntimeError, match="database unavailable"):
        await service.get_current_profile("local_user")

    repository.upsert.assert_not_awaited()
