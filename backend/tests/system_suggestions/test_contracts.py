"""Schema tests for SuggestionProposal, DismissalRecord, DismissalKind."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from magi.system_suggestions.contracts import (
    DismissalKind,
    DismissalRecord,
    SuggestionProposal,
)


def test_dismissal_kind_enum_values() -> None:
    assert DismissalKind.TRANSIENT.value == "transient"
    assert DismissalKind.EXPLICIT.value == "explicit"
    assert DismissalKind.NEVER.value == "never"


def test_dismissal_record_round_trip() -> None:
    now = datetime.now(timezone.utc)
    rec = DismissalRecord(dedupe_key="browser_history", dismissed_at=now, kind=DismissalKind.EXPLICIT)
    dumped = rec.model_dump()
    reloaded = DismissalRecord.model_validate(dumped)
    assert reloaded.dedupe_key == "browser_history"
    assert reloaded.kind == DismissalKind.EXPLICIT


def test_suggestion_proposal_minimal_valid() -> None:
    proposal = SuggestionProposal(
        dedupe_key="browser_history",
        category="browser_history",
        plugin_ids=["chrome-history"],
        confidence=0.9,
        rationale={"zh": "测试", "en": "test"},
    )
    assert proposal.dedupe_key == "browser_history"
    assert proposal.plugin_ids == ["chrome-history"]
    assert proposal.confidence == 0.9


def test_suggestion_proposal_rejects_invalid_confidence() -> None:
    with pytest.raises(ValidationError):
        SuggestionProposal(
            dedupe_key="x",
            category="x",
            plugin_ids=["p"],
            confidence=1.5,
            rationale={"zh": "测试", "en": "test"},
        )


def test_suggestion_proposal_rejects_empty_plugin_ids() -> None:
    with pytest.raises(ValidationError):
        SuggestionProposal(
            dedupe_key="x",
            category="x",
            plugin_ids=[],
            confidence=0.5,
            rationale={"zh": "测试", "en": "test"},
        )
