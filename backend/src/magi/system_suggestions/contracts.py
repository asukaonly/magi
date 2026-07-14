"""Public contracts for the system suggestion subsystem."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class DismissalKind(StrEnum):
    """How the user dismissed a suggestion. Determines the TTL applied."""

    TRANSIENT = "transient"  # close ×: 7-day suppression
    EXPLICIT = "explicit"    # "先不用" button: 30-day suppression
    NEVER = "never"          # "don't ask again": permanent


class DismissalRecord(BaseModel):
    dedupe_key: str
    dismissed_at: datetime
    kind: DismissalKind
    title: str | None = None
    """Localized notification text the user saw, for a consistent restore list.

    Optional for backward compatibility with records persisted before this
    field existed; the restore UI falls back to a humanized dedupe_key.
    """


class SuggestionPlugin(BaseModel):
    """Plugin-owned display metadata carried with a suggestion."""

    plugin_id: str
    name: str
    name_i18n: dict[str, str] = Field(default_factory=dict)
    icon: str = ""
    installed: bool


class SuggestionProposal(BaseModel):
    """A single suggestion produced by the matcher.

    Multiple sibling plugins (e.g. chrome-history + safari-history both under
    browser_history) collapse into one SuggestionProposal with all matched
    plugins listed. The UI bundles them into a single side card.
    """

    dedupe_key: str
    category: str
    plugins: list[SuggestionPlugin] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: dict[str, str]
    """Locale → user-facing rationale text. At least 'zh' and 'en' expected."""
