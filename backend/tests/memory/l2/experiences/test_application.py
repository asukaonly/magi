"""Experience application calls preserve revision admission without HTTP."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from magi.memory.application_errors import MemoryApplicationError
from magi.memory.l2.experiences.application import set_draft_cover, update_draft
from magi.memory.l2.experiences.commands import ExperienceDraftUpdateRequest


@pytest.mark.asyncio
async def test_cover_revision_is_checked_before_writing_an_asset():
    upload = AsyncMock(return_value={"asset_ref": "new-cover"})
    l2 = SimpleNamespace(
        get_experience_draft=AsyncMock(
            return_value={
                "draft_id": "draft",
                "updated_at": 2.0,
                "status": "editing",
            }
        ),
        edit_experience_draft=AsyncMock(),
    )
    with pytest.raises(MemoryApplicationError) as error:
        await set_draft_cover(
            "draft", upload, expected_updated_at=1.0, memory=SimpleNamespace(l2=l2)
        )
    assert error.value.reason == "conflict"
    upload.assert_not_awaited()
    l2.edit_experience_draft.assert_not_awaited()


@pytest.mark.asyncio
async def test_draft_edit_requires_a_revision_for_non_http_callers():
    l2 = SimpleNamespace(edit_experience_draft=AsyncMock())
    with pytest.raises(MemoryApplicationError) as error:
        await update_draft(
            "draft", ExperienceDraftUpdateRequest(title="New title"), memory=SimpleNamespace(l2=l2)
        )
    assert error.value.reason == "precondition_required"
    l2.edit_experience_draft.assert_not_awaited()
