from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from magi.user_profile.models import UserProfileProjection
from magi.user_profile.query_service import UserProfileQueryService


@pytest.mark.asyncio
async def test_get_current_profile_rebuilds_projection_from_l2():
    repository = AsyncMock()
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
    repository.get.assert_not_called()
    repository.upsert.assert_awaited_once()
    assert projection.preferred_form_of_address == "子涵"