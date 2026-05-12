"""User profile projection contracts."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

DEFAULT_USER_ID = "local_user"
PROFILE_ENTITY_TYPE = "user"

PROFILE_ASSERTION_FAMILIES = (
    "identity_profile",
    "communication_profile",
    "preference_profile",
    "state_profile",
)
PROFILE_ASSERTION_STATES = ("stable", "corroborated", "tentative")


class UserProfileProjection(BaseModel):
    """Current product-facing profile view derived from L2 assertions."""

    user_id: str = DEFAULT_USER_ID
    entity_id: str = f"user:{DEFAULT_USER_ID}"
    display_name: str = ""
    preferred_form_of_address: str = ""
    real_name: str = ""
    birth_date: str = ""
    birth_year: int | None = None
    age_years: int | None = None
    age_as_of: str = ""
    locale: str = ""
    timezone: str = ""
    home_location: str = ""
    communication: dict[str, Any] = Field(default_factory=dict)
    identity: dict[str, Any] = Field(default_factory=dict)
    preferences: dict[str, Any] = Field(default_factory=dict)
    state: dict[str, Any] = Field(default_factory=dict)
    field_sources: dict[str, Any] = Field(default_factory=dict)
    field_conflicts: dict[str, Any] = Field(default_factory=dict)
    completeness_score: float = 0.0
    refreshed_at: float = 0.0
    created_at: float = 0.0
    updated_at: float = 0.0


class ProfileUpdatePatch(BaseModel):
    """User-authored profile settings patch."""

    real_name: str | None = None
    birth_date: str | None = None
    preferred_form_of_address: str | None = None
    disallowed_forms_of_address: list[str] | None = None
    locale: str | None = None
    timezone: str | None = None
    home_location: str | None = None