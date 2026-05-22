"""Phase 5 north star: raw entity hashes must NEVER appear in the rendered
recall envelope. When the entity catalog has no canonical name for a given
entity_id, the finding is dropped — never rendered as a hash placeholder."""

from __future__ import annotations

from magi.memory.hybrid_retrieval.models import RetrievalPayload, RetrievalQuery
from magi.memory.retrieval_projection import project_historical_recall


def test_unresolved_entity_id_is_dropped_not_leaked():
    """A relationship finding referencing entity_id='74f953b57f75' with no
    canonical name in the resolver map must be dropped — the envelope must
    NOT contain the hash string anywhere in user-facing fields."""
    payload = RetrievalPayload(
        l2_relationships=[
            {
                "subject_id": "user:local_user",
                "predicate": "INTERESTED_IN",
                "object_id": "74f953b57f75",  # hash with no canonical name
                "confidence": 0.99,
                "status": "active",
            }
        ],
    )
    request = RetrievalQuery(query="who am I interested in")

    canonical_names = {"user:local_user": "asuka"}

    envelope = project_historical_recall(
        payload=payload,
        request=request,
        canonical_names=canonical_names,
    )

    from dataclasses import asdict
    envelope_str = str(asdict(envelope))
    assert "74f953b57f75" not in envelope_str, (
        f"raw entity hash leaked into envelope:\n{envelope_str[:500]}"
    )
    assert envelope.findings == [], (
        f"expected findings dropped due to unresolved object; got {envelope.findings}"
    )


def test_resolved_entity_id_is_rendered_with_canonical_name():
    """Counterpart: when canonical_names HAS the entity, the finding renders
    with the name (not the id)."""
    payload = RetrievalPayload(
        l2_relationships=[
            {
                "subject_id": "user:local_user",
                "predicate": "INTERESTED_IN",
                "object_id": "74f953b57f75",
                "confidence": 0.99,
                "status": "active",
            }
        ],
    )
    request = RetrievalQuery(query="who am I interested in")

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
    assert "字节跳动" in finding["statement"]
    assert "asuka" in finding["statement"]
    assert "74f953b57f75" not in finding["statement"]
