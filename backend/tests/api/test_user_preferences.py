"""Schema tests for UserPreferencesModel: first_conversation_completed field."""

from __future__ import annotations

from magi.api.routers.config_schemas import UserPreferencesModel


def test_first_conversation_completed_defaults_to_false() -> None:
    prefs = UserPreferencesModel()
    assert prefs.first_conversation_completed is False


def test_first_conversation_completed_round_trips_when_true() -> None:
    prefs = UserPreferencesModel(first_conversation_completed=True)
    dumped = prefs.model_dump()
    reloaded = UserPreferencesModel.model_validate(dumped)
    assert reloaded.first_conversation_completed is True


def test_existing_preferences_without_field_still_load() -> None:
    """A preferences blob saved before this field existed must still parse."""
    legacy_dump = {"onboarding_completed": True}
    prefs = UserPreferencesModel.model_validate(legacy_dump)
    assert prefs.first_conversation_completed is False
    assert prefs.onboarding_completed is True
