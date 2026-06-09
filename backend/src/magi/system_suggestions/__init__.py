"""System suggestion subsystem — keyword-driven in-chat plugin recommendations."""

from magi.system_suggestions.contracts import (
    DismissalKind,
    DismissalRecord,
    SuggestionProposal,
)

__all__ = ["DismissalKind", "DismissalRecord", "SuggestionProposal"]
