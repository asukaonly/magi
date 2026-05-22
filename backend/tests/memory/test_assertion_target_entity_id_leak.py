"""Regression test for C3: target_entity_id raw-hash leak in assertions.

When an assertion has empty claim/content/trait_value but a populated
target_entity_id, the renderer used to fall through and put the raw
entity_id into the user-facing statement. This is the same hash-leak
bug class Phase 5 was created to fix.

After the fix, target_entity_id must be resolved through canonical_names
just like the subject side; unresolved assertions are dropped."""

from __future__ import annotations

from magi.memory.hybrid_retrieval.models import RetrievalPayload, RetrievalQuery
from magi.memory.retrieval_projection import project_historical_recall


def test_assertion_with_unresolved_target_entity_id_is_dropped():
    """Assertion with target_entity_id but no claim/content/trait_value:
    when target_entity_id is NOT in canonical_names, the assertion must be
    dropped (NOT rendered with the raw hash as the value)."""
    payload = RetrievalPayload(
        l2_assertions=[
            {
                "entity_id": "user:local_user",
                "predicate": "INTERESTED_IN",
                # claim/content/trait_value all empty
                "target_entity_id": "74f953b57f75",  # hash with no canonical name
                "confidence": 0.9,
            }
        ],
    )
    request = RetrievalQuery(query="what am I interested in")

    canonical_names = {"user:local_user": "asuka"}  # missing the target

    envelope = project_historical_recall(
        payload=payload,
        request=request,
        canonical_names=canonical_names,
    )

    from dataclasses import asdict
    envelope_str = str(asdict(envelope))
    assert "74f953b57f75" not in envelope_str, (
        f"raw target_entity_id leaked into envelope:\n{envelope_str[:500]}"
    )
    # The assertion must be dropped (not rendered with hash)
    assert envelope.findings == [], (
        f"expected assertion dropped due to unresolved target; got {envelope.findings}"
    )


def test_assertion_with_resolved_target_entity_id_uses_canonical_name():
    """Counterpart: when target_entity_id is in canonical_names, the
    assertion renders with the canonical name as the value."""
    payload = RetrievalPayload(
        l2_assertions=[
            {
                "entity_id": "user:local_user",
                "predicate": "INTERESTED_IN",
                "target_entity_id": "74f953b57f75",
                "confidence": 0.9,
            }
        ],
    )
    request = RetrievalQuery(query="what am I interested in")

    canonical_names = {
        "user:local_user": "asuka",
        "74f953b57f75": "字节跳动",
    }

    envelope = project_historical_recall(
        payload=payload,
        request=request,
        canonical_names=canonical_names,
    )

    assert len(envelope.findings) == 1
    finding = envelope.findings[0]
    assert "字节跳动" in finding["statement"], (
        f"expected canonical name in statement; got {finding['statement']!r}"
    )
    assert "asuka" in finding["statement"]
    assert "74f953b57f75" not in finding["statement"]


def test_assertion_with_claim_uses_claim_not_target_entity_id():
    """When claim is populated, it wins over target_entity_id (no resolution
    needed for free-text claim values)."""
    payload = RetrievalPayload(
        l2_assertions=[
            {
                "entity_id": "user:local_user",
                "predicate": "PREFERS",
                "claim": "rust over go",
                "target_entity_id": "74f953b57f75",  # would have leaked if used
                "confidence": 0.9,
            }
        ],
    )
    request = RetrievalQuery(query="my preferences")
    canonical_names = {"user:local_user": "asuka"}

    envelope = project_historical_recall(
        payload=payload,
        request=request,
        canonical_names=canonical_names,
    )

    assert len(envelope.findings) == 1
    finding = envelope.findings[0]
    assert "rust over go" in finding["statement"]
    assert "74f953b57f75" not in finding["statement"]
