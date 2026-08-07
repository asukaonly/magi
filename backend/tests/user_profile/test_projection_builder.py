from __future__ import annotations

from datetime import date

from magi.user_profile.models import UserProfileProjection
from magi.user_profile.projection_builder import UserProfileProjectionBuilder
from magi.user_profile.projection_repository import UserProfileProjectionRepository


class _FakeL2:
    async def list_current_assertions(self, **kwargs):
        return [
            {
                "assertion_id": "a-real-name",
                "trait_family": "identity_profile",
                "trait_name": "identity.real_name",
                "trait_value": "明日香",
                "source_domain": "chat",
                "validation_state": "stable",
                "confidence_score": 0.9,
                "last_validated_at": 1_700_000_000,
            },
            {
                "assertion_id": "a-address",
                "trait_family": "communication_profile",
                "trait_name": "communication.address.preferred",
                "trait_value": "子涵",
                "source_domain": "settings_profile",
                "validation_state": "stable",
                "confidence_score": 1.0,
                "last_validated_at": 1_700_000_001,
            },
            {
                "assertion_id": "a-birth-date",
                "trait_family": "identity_profile",
                "trait_name": "identity.birth_date",
                "trait_value": "2000-05-06",
                "source_domain": "settings_profile",
                "validation_state": "stable",
                "confidence_score": 1.0,
                "last_validated_at": 1_700_000_002,
            },
        ]


class _ConflictingSourceL2:
    async def list_current_assertions(self, **kwargs):
        return [
            {
                "assertion_id": "a-external-name",
                "trait_family": "identity_profile",
                "trait_name": "identity.real_name",
                "trait_value": "浏览推断的名字",
                "source_domain": "external_activity",
                "validation_state": "stable",
                "confidence_score": 0.99,
                "last_validated_at": 1_700_000_010,
            },
            {
                "assertion_id": "a-user-name",
                "trait_family": "identity_profile",
                "trait_name": "identity.real_name",
                "trait_value": "用户自己说的名字",
                "source_domain": "user_authored",
                "validation_state": "stable",
                "confidence_score": 0.7,
                "last_validated_at": 1_700_000_000,
            },
        ]


async def test_projection_builder_selects_profile_assertions_and_derives_age():
    projection = await UserProfileProjectionBuilder(_FakeL2()).build("local_user")

    assert projection.display_name == "子涵"
    assert projection.real_name == "明日香"
    assert projection.preferred_form_of_address == "子涵"
    assert projection.birth_year == 2000
    assert projection.age_years == date.today().year - 2000 - (
        (date.today().month, date.today().day) < (5, 6)
    )
    assert projection.field_sources["preferred_form_of_address"]["source"] == "settings_profile"
    assert projection.identity["birth_date"] == "2000-05-06"
    assert projection.input_assertion_highwater == 1_700_000_002


async def test_projection_builder_prefers_user_authored_profile_assertions():
    projection = await UserProfileProjectionBuilder(_ConflictingSourceL2()).build("local_user")

    assert projection.real_name == "用户自己说的名字"
    assert projection.field_sources["real_name"]["source"] == "user_authored"


async def test_profile_projection_repository_roundtrips_assertion_highwater(tmp_path):
    repository = UserProfileProjectionRepository(str(tmp_path / "memory.db"))

    await repository.upsert(
        UserProfileProjection(
            user_id="local_user",
            entity_id="user:local_user",
            input_assertion_highwater=42.0,
        )
    )

    loaded = await repository.get("local_user")
    assert loaded is not None
    assert loaded.input_assertion_highwater == 42.0
