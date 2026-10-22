"""Exercise the unified path with real source registration and acceptance storage."""
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from magi_plugin_sdk import PluginConnection, SourceCoverage, SourceCoverageScope
from magi_plugin_sdk.source_query import SourceQueryCapabilities, SourceQueryResult, SourceEvidence
from magi_plugin_sdk.sources import SourceSpec
from magi.awareness.source_store import SourceStore
from magi.awareness.retrieval.service import PersonalRetrievalService
from magi.awareness.retrieval.policy import assess_coverage
from magi.memory.hybrid_retrieval.models import RetrievalPayload, RetrievalQuery
from magi.plugins.sources import SourceRegistry


def make_source(registry, connections, name="work", provider="gmail", query=None):
    connection = PluginConnection(connection_id=name, plugin_id=provider, display_name=name, enabled=True)
    connections[name] = connection
    source = SimpleNamespace(source_id="mail", source_type="mail", connection=connection,
                             query_source=query or AsyncMock())
    registry.register(provider, name + ":mail", source, SourceSpec(
        source_id=name + ":mail", display_name=name, domain="mail",
        query_capabilities=SourceQueryCapabilities(provider=provider, operations=["search", "read", "thread"], fields=["content", "thread", "labels"]),
        metadata={"connection_id": name},
    ))
    return source


def local_event(account="work", text="A travel plan", version="1"):
    return {"event_id": "event-" + account, "content": text, "source": "mail", "timestamp": 100,
            "metadata": {"source_connection_id": account, "source_id": "mail", "source_object_id": "m1",
                         "source_object_version": version, "source_content_fields": ["content"], "thread_id": "t1"}}


def local_payload(events=(), **shape):
    return RetrievalPayload(l1_events=list(events), trace={"recall_shape": {
        "domain_hint": "mail", "operation": "search", "search_query": "travel", **shape}})


def source_result(request, *, items=True, snapshot=True):
    now = time.time()
    return SourceQueryResult(items=[SourceEvidence(object_id="m1", version="2", text="Updated travel plan",
        occurred_at=100, thread_id="t1", fields=request.fields)] if items else [],
        coverage=SourceCoverage(scope=request.scope, fields=request.fields, checked_at=now,
            snapshot_as_of=now if snapshot else None, consistency="snapshot" if snapshot else "best_effort",
            completeness="complete"))


def setup_service(tmp_path, payload):
    registry, connections = SourceRegistry(), {}
    memory = SimpleNamespace(query=AsyncMock(return_value=payload), memory_db_path="unused")
    governance = SimpleNamespace(capture=AsyncMock(return_value="epoch"), unchanged=AsyncMock(return_value=True),
                                 visible=AsyncMock(return_value=True))
    service = PersonalRetrievalService(memory=memory, registry=registry, store=SourceStore(tmp_path / "sources.db"),
        get_connection=connections.get, governance=governance)
    return service, registry, connections


@pytest.mark.asyncio
async def test_stable_historical_mail_uses_memory_without_network(tmp_path):
    service, registry, connections = setup_service(tmp_path, local_payload([local_event()]))
    source = make_source(registry, connections)
    result = await service.retrieve(RetrievalQuery(query="Find my travel plan", limit=10))
    assert result["recall"]["answerability"] == "sufficient"
    source.query_source.assert_not_called()


@pytest.mark.asyncio
async def test_current_reply_targets_thread_and_deduplicates_stored_message(tmp_path):
    service, registry, connections = setup_service(tmp_path, local_payload([local_event()], freshness="current", required_fields=["thread"]))
    source = make_source(registry, connections, query=AsyncMock(side_effect=source_result))
    result = await service.retrieve(RetrievalQuery(query="Any reply now?", limit=10))
    request = source.query_source.call_args.args[0]
    assert request.operation == "thread" and request.scope.object_ids == ["t1"]
    assert result["recall"]["freshness"]["satisfied"]
    assert len(result["recall"]["findings"]) == 1
    assert result["recall"]["findings"][0]["origin"] == "source"


@pytest.mark.asyncio
async def test_explicit_provider_cannot_return_other_account_or_unproven_derived_fact(tmp_path):
    payload = local_payload([local_event("work"), local_event("private", text="Private QQ secret")])
    payload.l2_assertions = [{"statement": "Secret derived fact", "natural_summary": "Secret derived fact"}]
    service, registry, connections = setup_service(tmp_path, payload)
    gmail = make_source(registry, connections)
    qq = make_source(registry, connections, name="private", provider="qq")
    result = await service.retrieve(RetrievalQuery(query="travel", limit=10), source_scope={"provider": "gmail"})
    assert "Private QQ" not in str(result["recall"])
    assert "Secret derived" not in str(result["recall"])
    qq.query_source.assert_not_called()
    gmail.query_source.assert_not_called()


@pytest.mark.asyncio
async def test_unavailable_source_cannot_prove_current_absence(tmp_path):
    service, registry, connections = setup_service(tmp_path, local_payload(freshness="current", operation="existence"))
    make_source(registry, connections, query=AsyncMock(side_effect=TimeoutError()))
    recall = (await service.retrieve(RetrievalQuery(query="Any new replies?")))["recall"]
    assert recall["insufficient_evidence"]
    assert recall["answering_hints"]["must_not_claim_absence"]
    assert recall["source_checks"][0]["reason"] == "source_timeout"


@pytest.mark.asyncio
async def test_memory_only_and_unspecified_domain_do_not_fan_out(tmp_path):
    service, registry, connections = setup_service(tmp_path, local_payload(freshness="current"))
    source = make_source(registry, connections)
    await service.retrieve(RetrievalQuery(query="Any updates?"), retrieval_policy="memory_only")
    source.query_source.assert_not_called()
    service.memory.query.return_value = RetrievalPayload()
    await service.retrieve(RetrievalQuery(query="What was that?"))
    source.query_source.assert_not_called()


@pytest.mark.asyncio
async def test_forgetting_and_revocation_during_read_suppress_results(tmp_path):
    service, registry, connections = setup_service(tmp_path, local_payload())
    source = make_source(registry, connections)
    async def revoke(request):
        connections["work"] = connections["work"].model_copy(update={"enabled": False})
        return source_result(request)
    source.query_source.side_effect = revoke
    recall = (await service.retrieve(RetrievalQuery(query="travel")))["recall"]
    assert recall["findings"] == [] and recall["insufficient_evidence"]
    connections["work"] = source.connection
    source.query_source.side_effect = source_result
    service.governance.visible.return_value = False
    recall = (await service.retrieve(RetrievalQuery(query="travel")))["recall"]
    assert recall["findings"] == [] and recall["insufficient_evidence"]
    service.governance.unchanged.return_value = False
    recall = (await service.retrieve(RetrievalQuery(query="travel")))["recall"]
    assert recall["findings"] == []


def test_freshness_is_distinct_from_occurrence_age_and_scope():
    scope = SourceCoverageScope(start=100, end=200)
    coverage = SourceCoverage(scope=scope, checked_at=250, completeness="complete")
    assert assess_coverage(coverage, scope, ["content"], now=10000, current=False)["satisfied"]
    assert not assess_coverage(coverage, scope, ["content"], now=10000, current=True)["satisfied"]
    assert not assess_coverage(coverage, SourceCoverageScope(), ["content"], now=300, current=False)["satisfied"]


@pytest.mark.asyncio
@pytest.mark.parametrize("snapshot", [False, True])
async def test_count_requires_complete_snapshot_and_counts_objects_only(tmp_path, snapshot):
    service, registry, connections = setup_service(tmp_path, local_payload([local_event()], operation="count"))
    make_source(registry, connections, query=AsyncMock(side_effect=lambda r: source_result(r, snapshot=snapshot)))
    recall = (await service.retrieve(RetrievalQuery(query="How many travel emails?", limit=10)))["recall"]
    assert recall["coverage"]["can_claim_total"] is snapshot
    assert recall["insufficient_evidence"] is (not snapshot)
    assert recall["coverage"]["total_count"] == (1 if snapshot else None)


@pytest.mark.asyncio
async def test_partial_pages_never_prove_count_or_absence(tmp_path):
    service, registry, connections = setup_service(tmp_path, local_payload(operation="count"))
    async def page(request):
        result = source_result(request)
        return result.model_copy(update={"coverage": result.coverage.model_copy(update={"completeness": "partial"}),
            "next_page_token": str(int(request.page_token or "0") + 1)})
    source = make_source(registry, connections, query=AsyncMock(side_effect=page))
    recall = (await service.retrieve(RetrievalQuery(query="Count mail")))["recall"]
    assert source.query_source.call_count == 3
    assert not recall["coverage"]["can_claim_total"]
    assert recall["answering_hints"]["must_not_claim_absence"]


@pytest.mark.asyncio
async def test_unloaded_connection_can_use_retained_historical_scope(tmp_path):
    event = local_event()
    event["metadata"].update(source_domain="mail", source_provider="gmail")
    service, registry, connections = setup_service(tmp_path, local_payload([event]))
    connections["work"] = PluginConnection(connection_id="work", plugin_id="gmail", display_name="work", enabled=False)
    recall = (await service.retrieve(RetrievalQuery(query="Old travel plan"), source_scope={"provider": "gmail"}))["recall"]
    assert recall["answerability"] == "sufficient"
    assert len(recall["findings"]) == 1


def test_recall_shape_round_trip_preserves_required_fields():
    from magi.memory.hybrid_retrieval.recall_shape import RecallShape, parse_recall_shape
    shape = RecallShape(domain_hint="mail", required_fields=("thread", "labels"))
    assert parse_recall_shape(shape.to_dict()).required_fields == ("thread", "labels")


@pytest.mark.asyncio
async def test_current_reply_discovers_then_reads_thread_within_source_budget(tmp_path):
    service, registry, connections = setup_service(tmp_path, local_payload(freshness="current", required_fields=["thread"]))
    source = make_source(registry, connections, query=AsyncMock(side_effect=source_result))
    recall = (await service.retrieve(RetrievalQuery(query="Reply to travel plan?", limit=10)))["recall"]
    requests = [call.args[0] for call in source.query_source.call_args_list]
    assert [r.operation for r in requests] == ["search", "thread"]
    assert "thread" not in requests[0].fields and "thread" in requests[1].fields
    assert recall["answerability"] == "sufficient"
    assert not recall["coverage"]["can_claim_total"]
    assert recall["source_checks"][0]["discovery_complete"]


@pytest.mark.asyncio
async def test_existing_structured_local_count_needs_no_live_source(tmp_path):
    payload = RetrievalPayload(structured_results=[{"domain": "photo", "status": "found", "summary": {"photo_count": 0, "session_count": 0},
        "coverage": {"kind": "exhaustive", "can_claim_total": True, "total_count": 0}}],
        trace={"recall_shape": {"domain_hint": "photo", "operation": "count"}})
    service, registry, connections = setup_service(tmp_path, payload)
    source = make_source(registry, connections)
    recall = (await service.retrieve(RetrievalQuery(query="How many photos yesterday?")))["recall"]
    assert recall["status"] == "found" and recall["answerability"] == "sufficient"
    assert recall["coverage"]["total_count"] == 0 and recall["coverage"]["can_claim_total"]
    assert recall["source_checks"] == []
    source.query_source.assert_not_called()
