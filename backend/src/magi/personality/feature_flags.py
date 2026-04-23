"""Helpers for resolving global personality runtime feature flags."""

from __future__ import annotations

from dataclasses import dataclass

from ..config import get_config


@dataclass(frozen=True, slots=True)
class PersonalityFeatureFlags:
    """Normalized runtime switches for personality memory-derived features."""

    state_memory_enabled: bool
    state_transition_enabled: bool
    deep_persona_enabled: bool


def get_personality_feature_flags() -> PersonalityFeatureFlags:
    """Return normalized personality feature flags from global runtime config."""
    config = get_config()
    settings = getattr(config.agent, "personality", None)

    state_memory_enabled = bool(
        getattr(settings, "enable_state_memory", getattr(settings, "enable_evolution", True))
    )
    state_transition_enabled = bool(getattr(settings, "enable_state_transition", True))
    deep_persona_enabled = bool(getattr(settings, "enable_deep_persona", True))

    if not state_memory_enabled:
        state_transition_enabled = False
        deep_persona_enabled = False

    return PersonalityFeatureFlags(
        state_memory_enabled=state_memory_enabled,
        state_transition_enabled=state_transition_enabled,
        deep_persona_enabled=deep_persona_enabled,
    )