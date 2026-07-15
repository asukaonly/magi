from __future__ import annotations

from pathlib import Path

from magi.user_profile.command_service import UserProfileCommandService
from magi.user_profile.models import ProfileUpdatePatch
from magi.user_profile.portrait_projection_builder import UserPortraitProjectionBuilder
from magi.user_profile.portrait_projection_repository import UserPortraitProjectionRepository
from magi.user_profile.projection_builder import UserProfileProjectionBuilder
from magi.user_profile.projection_repository import UserProfileProjectionRepository
from magi.user_profile.query_service import UserProfileQueryService


class _FakeL1:
    def __init__(self):
        self.events = []

    async def store(self, event):
        self.events.append(event)
        return event.event_id


class _FakeL2:
    def __init__(self):
        self.db_path = "unused"
        self.assertions = []
        self.feedback = []

    async def upsert_assertion_candidate(self, candidate):
        assertion_id = f"a-{len(self.assertions) + 1}"
        self.assertions.append({**candidate, "assertion_id": assertion_id, "updated_at": candidate["last_validated_at"]})
        return assertion_id

    async def apply_user_feedback(self, assertion_id, feedback):
        self.feedback.append((assertion_id, feedback))

    async def list_current_assertions(self, **kwargs):
        return self.assertions


class _FakeUnifiedMemory:
    def __init__(self):
        self.l1 = _FakeL1()
        self.l2 = _FakeL2()


class _StaticQueryService:
    def __init__(self, profile):
        self.profile = profile

    async def refresh_profile(self, user_id):
        return self.profile

    async def get_current_profile(self, user_id):
        return self.profile


async def test_command_service_writes_profile_assertions_and_refreshes_projection(tmp_path: Path):
    unified_memory = _FakeUnifiedMemory()
    repository = UserProfileProjectionRepository(str(tmp_path / "memory.db"))
    portrait_repository = UserPortraitProjectionRepository(str(tmp_path / "memory.db"))
    query_service = UserProfileQueryService(
        repository=repository,
        builder=UserProfileProjectionBuilder(unified_memory.l2),
    )
    command_service = UserProfileCommandService(
        unified_memory=unified_memory,
        query_service=query_service,
        portrait_repository=portrait_repository,
        portrait_builder=UserPortraitProjectionBuilder(unified_memory.l2),
    )

    projection = await command_service.update_from_settings(
        ProfileUpdatePatch(
            real_name="明日香",
            birth_date="2000-05-06",
            preferred_form_of_address="子涵",
        )
    )

    trait_names = {assertion["trait_name"] for assertion in unified_memory.l2.assertions}
    assert "identity.real_name" in trait_names
    assert "identity.birth_date" in trait_names
    assert "identity.birth_year" in trait_names
    assert "communication.address.preferred" in trait_names
    assert len(unified_memory.l1.events) == 1
    assert all(feedback == "confirmed" for _, feedback in unified_memory.l2.feedback)
    assert projection.display_name == "子涵"
    assert projection.birth_year == 2000

    portrait = await portrait_repository.get("local_user")
    assert portrait is not None
    portrait_text = str(portrait.world) + "\n" + "\n".join(portrait.prompt_summary)
    assert "明日香" in portrait_text
    assert "子涵" in portrait_text


async def test_command_service_refreshes_portrait_with_strong_profile_projection(tmp_path: Path):
    unified_memory = _FakeUnifiedMemory()
    profile = await UserProfileProjectionBuilder(unified_memory.l2).build("local_user")
    profile = profile.model_copy(update={
        "display_name": "子涵",
        "preferred_form_of_address": "子涵",
        "home_location": "杭州",
        "updated_at": 200.0,
        "refreshed_at": 200.0,
    })
    portrait_repository = UserPortraitProjectionRepository(str(tmp_path / "memory.db"))
    command_service = UserProfileCommandService(
        unified_memory=unified_memory,
        query_service=_StaticQueryService(profile),
        portrait_repository=portrait_repository,
        portrait_builder=UserPortraitProjectionBuilder(unified_memory.l2),
    )

    await command_service.refresh_from_memory("local_user")

    portrait = await portrait_repository.get("local_user")
    assert portrait is not None
    world_text = str(portrait.world)
    assert "子涵" in world_text
    assert "杭州" in world_text
