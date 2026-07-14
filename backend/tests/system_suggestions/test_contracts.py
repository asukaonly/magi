"""Schema tests for SuggestionProposal, DismissalRecord, DismissalKind."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from magi.system_suggestions.contracts import (
    DismissalKind,
    DismissalRecord,
    SuggestionPlugin,
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
        plugins=[
            SuggestionPlugin(
                plugin_id="chrome-history",
                name="Chrome History",
                name_i18n={"zh-CN": "Chrome 浏览器历史"},
                icon="brand:googlechrome",
                installed=True,
            )
        ],
        confidence=0.9,
        rationale={"zh": "测试", "en": "test"},
    )
    assert proposal.dedupe_key == "browser_history"
    assert proposal.plugins[0].name_i18n["zh-CN"] == "Chrome 浏览器历史"
    assert proposal.confidence == 0.9


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
