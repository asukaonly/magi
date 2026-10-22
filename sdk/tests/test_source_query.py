"""Coverage claims and query values survive the actual worker wire boundary."""
import pytest
from pydantic import ValidationError

from magi_plugin_sdk import SourceCoverage, SourceCoverageScope, SourceChangeBatch
from magi_plugin_sdk.source_query import SourceEvidence, SourceQueryCapabilities, SourceQueryRequest, SourceQueryResult
from magi_plugin_sdk.sources import SourceSpec
from magi_plugin_sdk.transport import encode, decode


def test_query_wire_round_trip():
    values = [
        SourceSpec(source_id="mail", display_name="Mail", query_capabilities=SourceQueryCapabilities(provider="gmail")),
        SourceQueryRequest(scope=SourceCoverageScope(query="trip", start=10, end=20)),
        SourceQueryResult(items=[SourceEvidence(object_id="m1", version="v1", text="Trip")],
                          coverage=SourceCoverage(checked_at=30, completeness="complete")),
    ]
    for value in values:
        assert decode(encode(value)) == value


def test_partial_page_and_unknown_snapshot_cannot_claim_completeness():
    with pytest.raises(ValidationError):
        SourceQueryResult(next_page_token="more", coverage=SourceCoverage(checked_at=1, completeness="complete"))
    with pytest.raises(ValidationError):
        SourceChangeBatch(complete=False, coverage=SourceCoverage(checked_at=1, completeness="complete"))
    with pytest.raises(ValidationError):
        SourceCoverage(checked_at=1, consistency="snapshot")
    with pytest.raises(ValidationError):
        SourceCoverage(checked_at=float("nan"))
    with pytest.raises(ValidationError):
        SourceCoverage(checked_at=1, completeness="complete", gaps=["missing_body"])


def test_object_reads_are_bounded_and_have_no_authority_arguments():
    with pytest.raises(ValidationError):
        SourceQueryRequest(operation="read")
    with pytest.raises(ValidationError):
        SourceQueryRequest(connection_id="other-account")
