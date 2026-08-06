"""Fresh-input regression fixtures for the L2 rearchitecture."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from magi.memory.l2.models import L2BatchEvent, L2EventWindow, L2Phase1Result
from magi.memory.l2.pipeline.claim_grounding import ground_phase1_fact_claims
from magi.memory.l2.pipeline.claim_persistence import _evidence_locator


_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "claim_assertion_rearchitecture.json"


def _load_cases() -> list[dict[str, Any]]:
    with _FIXTURE_PATH.open(encoding="utf-8") as fixture_file:
        payload = json.load(fixture_file)
    assert isinstance(payload, list)
    return payload


@pytest.mark.parametrize("case", _load_cases(), ids=lambda case: str(case["name"]))
def test_fresh_input_claims_have_exact_stable_grounding(case: dict[str, Any]) -> None:
    event = L2BatchEvent.from_dict(case["event"])
    result = L2Phase1Result.from_dict(case["phase1"])

    stats = ground_phase1_fact_claims(result, L2EventWindow(events=[event]))

    assert stats == {
        "kept": 1,
        "rejected": 0,
        "rebound": int(bool(case["phase1"]["fact_claims"][0]["supporting_event_ids"])),
    }
    assert len(result.fact_claims) == 1
    claim = result.fact_claims[0]
    expected = case["expected"]
    assert claim.claim_id == "claim:1"
    assert claim.predicate == expected["predicate"]
    assert claim.object_ref == expected["object_ref"]
    assert claim.object_type == expected["object_type"]
    assert claim.fact_kind.value == expected["fact_kind"]
    assert claim.evidence_text == expected["evidence_text"]
    assert claim.supporting_event_ids == expected["supporting_event_ids"]

    locator = _evidence_locator(
        event.content,
        claim.evidence_text,
        event_type=event.event_type,
    )
    start = event.content.index(claim.evidence_text)
    assert locator["start"] == start
    assert locator["end"] == start + len(claim.evidence_text)
    assert locator["quote_hash"] == hashlib.sha256(
        claim.evidence_text.encode("utf-8")
    ).hexdigest()
    assert locator.get("attribution") == expected["attribution"]


@pytest.mark.parametrize("case", _load_cases(), ids=lambda case: str(case["name"]))
def test_fresh_input_claim_ids_do_not_depend_on_prior_database_state(
    case: dict[str, Any],
) -> None:
    event_window = L2EventWindow(events=[L2BatchEvent.from_dict(case["event"])])
    first = L2Phase1Result.from_dict(case["phase1"])
    second = L2Phase1Result.from_dict(case["phase1"])

    ground_phase1_fact_claims(first, event_window)
    ground_phase1_fact_claims(second, event_window)

    assert [claim.to_dict() for claim in first.fact_claims] == [
        claim.to_dict() for claim in second.fact_claims
    ]
