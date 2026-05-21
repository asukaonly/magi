from magi.memory.evidence import EvidenceClass
from magi.memory.hybrid_retrieval.evidence_routing import infer_allowed_evidence_classes


def test_self_preference_routes_to_declared_only():
    result = infer_allowed_evidence_classes(
        predicate_family="preference", subject_scope="self"
    )
    assert result == {EvidenceClass.USER_SELF_REPORT.label}


def test_self_profile_fact_routes_to_declared_only():
    result = infer_allowed_evidence_classes(
        predicate_family="profile_fact", subject_scope="self"
    )
    assert result == {EvidenceClass.USER_SELF_REPORT.label}


def test_activity_allows_observation():
    result = infer_allowed_evidence_classes(
        predicate_family="activity", subject_scope="self"
    )
    assert EvidenceClass.EXTERNAL_OBSERVATION.label in result
    assert EvidenceClass.USER_SELF_REPORT.label in result


def test_unknown_family_returns_no_filter():
    assert (
        infer_allowed_evidence_classes(predicate_family=None, subject_scope=None)
        is None
    )
