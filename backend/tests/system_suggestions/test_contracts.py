"""Schema tests for SuggestionProposal, DismissalRecord, DismissalKind."""

from __future__ import annotations


import pytest
from pydantic import ValidationError

from magi.system_suggestions.contracts import (
    SuggestionProposal,
)


def test_suggestion_proposal_rejects_invalid_confidence() -> None:
    with pytest.raises(ValidationError):
        SuggestionProposal(
            dedupe_key="x",
            category="x",
            plugins=[{"plugin_id": "p", "name": "P", "installed": True}],
            confidence=1.5,
            rationale={"zh": "测试", "en": "test"},
        )


def test_suggestion_proposal_rejects_empty_plugins() -> None:
    with pytest.raises(ValidationError):
        SuggestionProposal(
            dedupe_key="x",
            category="x",
            plugins=[],
            confidence=0.5,
            rationale={"zh": "测试", "en": "test"},
        )
