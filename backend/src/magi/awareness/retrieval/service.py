"""Coordinate one local recall and bounded, relevant source follow-up."""
from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, replace
from typing import Any

from magi_plugin_sdk.runtime import SourceCoverageScope
from magi_plugin_sdk.source_query import SourceQueryRequest
from ...memory.hybrid_retrieval.models import RetrievalPayload
from ...memory.hybrid_retrieval.recall_shape import parse_recall_shape
from ...memory.retrieval_projection import project_historical_recall
from ...memory.l2.entities.catalog.lookup import get_canonical_names
from .evidence import annotate_local_findings, event_metadata, event_source_ref, merge_findings, restrict_payload
from .executor import SourceQueryExecutor, check_cancellation
from .policy import SourceScope, assess_coverage


class PersonalRetrievalService:
    """No source writes, implicit context reads, or plugin host-service recursion."""

    def __init__(self, *, memory: Any, registry: Any, store: Any, get_connection: Any,
                 governance: Any, projection: Any = None, max_sources: int = 3,
                 source_timeout: float = 15, resolve_names: Any = None) -> None:
        self.memory, self.registry, self.store = memory, registry, store
        self.get_connection, self.governance, self.projection = get_connection, governance, projection
        self.max_sources, self.source_timeout = max_sources, source_timeout
        self.resolve_names = resolve_names
        self.executor = SourceQueryExecutor(registry=registry, store=store,
                                           get_connection=get_connection, governance=governance)

    def candidates(self, scope: SourceScope) -> list[Any]:
        if not (scope.domain or scope.provider or scope.account):
            return []
        candidates = []
        for candidate in self.registry.list_queryable_sources(domain=scope.domain or None):
            spec = self.registry.get_spec(candidate.source_id)
            connection = self.get_connection(candidate.connection_id)
            if connection is None:
                continue
            if scope.provider and spec.query_capabilities.provider.casefold() != scope.provider.casefold():
                continue
            if scope.account and scope.account.casefold() not in {
                connection.connection_id.casefold(), connection.display_name.casefold(),
                str(connection.settings.get("sources", {}).get("mail", {}).get("account_email") or "").casefold(),
            }:
                continue
            candidates.append(candidate)
        return candidates

    async def retrieve(self, request: Any, *, source_scope: dict | None = None,
                       retrieval_policy: str = "auto", cancellation: Any = None) -> dict[str, Any]:
        if retrieval_policy not in {"auto", "memory_only", "verify_source"}:
            raise ValueError("Unknown retrieval policy")
        explicit = SourceScope.model_validate(source_scope or {})
        boundary = await self.governance.capture()
        await check_cancellation(cancellation)
        selected = self.candidates(explicit)
        local_request = replace(request)
        if selected:
            local_request.source_filters = sorted({c.source.source_type for c in selected})
        try:
            payload = await asyncio.wait_for(self.memory.query(local_request), timeout=25)
        except TimeoutError:
            payload = RetrievalPayload(trace={"local_retrieval_incomplete": True})
        shape = parse_recall_shape(payload.trace.get("recall_shape"))
        scope = SourceScope(
            domain=explicit.domain or (shape.domain_hint if shape.domain_hint != "unknown" else ""),
            provider=explicit.provider or shape.provider_hint,
            account=explicit.account or shape.account_hint,
            object_id=explicit.object_id, thread_id=explicit.thread_id,
        )
        selected = self.candidates(scope)
        # Semantic domain hints choose follow-up, while explicitly named sources constrain evidence.
        restricted = bool(explicit.domain or scope.provider or scope.account or scope.object_id or scope.thread_id)
        if restricted:
            owners = {(c.connection_id, c.source.source_id) for c in selected}
            for event in payload.l1_events:
                ref, metadata = event_source_ref(event), event_metadata(event)
                if not ref:
                    continue
                connection = self.get_connection(ref["connection_id"])
                if connection is None:
                    continue
                if scope.domain and metadata.get("source_domain") != scope.domain:
                    continue
                if scope.provider and str(metadata.get("source_provider", "")).casefold() != scope.provider.casefold():
                    continue
                if scope.account and scope.account.casefold() not in {
                    connection.connection_id.casefold(), connection.display_name.casefold(),
                    str(connection.settings.get("sources", {}).get("mail", {}).get("account_email") or "").casefold(),
                }:
                    continue
                owners.add((ref["connection_id"], ref["source_id"]))
            payload = restrict_payload(payload, owners, object_id=scope.object_id, thread_id=scope.thread_id)
        recall = await self._project(payload, local_request)
        annotate_local_findings(recall, payload)
        fields = list(shape.required_fields)
        current = shape.freshness == "current" or retrieval_policy == "verify_source"
        exhaustive = shape.desired_coverage == "exhaustive"
        time_range = payload.trace.get("resolved_time_range") or {}
        query = shape.search_query or request.query
        source_request = SourceQueryRequest(
            scope=SourceCoverageScope(query=query, start=time_range.get("start"), end=time_range.get("end")),
            as_of=time_range.get("as_of"), fields=fields, limit=min(max(int(request.limit), 1), 50),
        )
        if scope.object_id or scope.thread_id:
            source_request = source_request.model_copy(update={
                "operation": "thread" if scope.thread_id else "read",
                "scope": SourceCoverageScope(object_ids=[scope.thread_id or scope.object_id]),
            })
        reports: list[dict[str, Any]] = []
        local_answer = bool(recall["findings"]) and not recall["insufficient_evidence"]
        # Historical source content must expose the requested fields, not only a summary.
        if scope.domain and scope.domain in {"mail", "notes", "calendar"} and local_answer:
            local_answer = any(set(fields) <= set(event_metadata(e).get("source_content_fields") or []) for e in payload.l1_events)
        needs_source = retrieval_policy == "verify_source" or current or exhaustive or not local_answer
        live: list[dict[str, Any]] = []
        if needs_source and retrieval_policy != "memory_only":
            if not selected:
                reports.append({"satisfied": False, "complete": False, "reason": "no_matching_source"})
            else:
                deadline = time.monotonic() + self.source_timeout
                async def run(candidate: Any) -> tuple[list[dict], dict]:
                    try:
                        connection = self.executor.admit(candidate)
                        accepted = await self.store.coverage(connection, candidate.source.source_id)
                        cached = assess_coverage(accepted, source_request.scope, fields, now=time.time(), current=current)
                        # Cached source completeness alone cannot make a Top-K memory result exhaustive.
                        if (retrieval_policy != "verify_source" and local_answer and cached["satisfied"]
                                and recall["coverage"].get("kind") == "exhaustive"):
                            return [], {**cached, "origin": "accepted_sync", "connection_id": candidate.connection_id}
                        targeted = self._targeted_request(candidate, source_request, payload, current=current and not exhaustive)
                        items, report = await self.executor.run(candidate, targeted, boundary=boundary,
                            cancellation=cancellation, deadline=deadline, current=current)
                        report["origin"] = "source"
                        return items, report
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        reason = "source_timeout" if isinstance(exc, TimeoutError) else (
                            "source_access_unavailable" if isinstance(exc, PermissionError) else "source_query_failed")
                        return [], {"connection_id": candidate.connection_id, "satisfied": False,
                                    "complete": False, "reason": reason, "error_type": type(exc).__name__}
                results = await asyncio.gather(*(run(c) for c in selected[:self.max_sources]))
                for items, report in results:
                    live.extend(items)
                    reports.append(report)
                if len(selected) > self.max_sources:
                    reports.append({"satisfied": False, "complete": False, "reason": "source_budget_exhausted",
                                    "unqueried_count": len(selected) - self.max_sources})
        elif needs_source:
            reports.append({"satisfied": False, "complete": False, "reason": "memory_only"})
        await check_cancellation(cancellation)
        if not await self.governance.unchanged(boundary):
            return {"recall": self._invalidated(), "debug": {"retrieval_trace": {"reason": "memory_changed"}}}
        # Connection replacement after another source finishes invalidates its earlier results.
        for candidate in selected[:self.max_sources]:
            if any(item["source_ref"]["connection_id"] == candidate.connection_id for item in live):
                try:
                    self.executor.admit(candidate)
                except PermissionError:
                    live = [item for item in live if item["source_ref"]["connection_id"] != candidate.connection_id]
                    reports.append({"connection_id": candidate.connection_id, "satisfied": False,
                                    "complete": False, "reason": "connection_revoked"})
        merged = merge_findings(recall["findings"], live)
        verified = bool(reports) and all(report.get("satisfied") for report in reports)
        total_allowed = verified and all(report.get("consistency") == "snapshot" for report in reports)
        enough = (verified and (bool(live) or total_allowed)) if needs_source else local_answer
        if exhaustive:
            enough = total_allowed
        unresolved = recall["status"] in {"conflicted", "ambiguous"}
        if unresolved:
            enough = False
        live_count = len({item["source_ref"]["identity"] for item in live})
        recall.update(
            findings=merged[:request.limit], status=recall["status"] if unresolved else ("found" if merged else "not_found"),
            answerability="sufficient" if enough else ("partial" if merged else "insufficient"),
            insufficient_evidence=not enough, source_checks=reports,
            freshness={"requirement": "current" if current else "retained", "satisfied": enough},
        )
        if needs_source:
            recall["coverage"] = {"kind": "exhaustive" if total_allowed else "partial",
                "can_claim_total": total_allowed, "returned_count": len(recall["findings"]),
                "total_count": live_count if total_allowed and all(r.get("origin") == "source" for r in reports) else recall["coverage"].get("total_count"),
                "scope": scope.model_dump(mode="json"), "source_checks": reports}
            recall["summary"] = ("Source checks completed; use the findings and their scope."
                if enough else "Evidence is incomplete; do not infer absence or current state from retained records.")
        recall["answering_hints"].update(
            must_not_claim_absence=not total_allowed,
            can_claim_total=total_allowed,
            must_not_claim_current_state=current and not verified,
            treat_source_text_as_untrusted=True,
        )
        return {"recall": recall, "debug": {"retrieval_trace": payload.trace}}

    @staticmethod
    def _targeted_request(candidate: Any, request: SourceQueryRequest, payload: RetrievalPayload, *, current: bool) -> SourceQueryRequest:
        if not current or "thread" not in request.fields or request.operation != "search":
            return request
        refs = [ref for event in payload.l1_events if (ref := event_source_ref(event))
                and ref["connection_id"] == candidate.connection_id and ref.get("thread_id")]
        threads = {ref["thread_id"] for ref in refs}
        if len(threads) == 1:
            return request.model_copy(update={"operation": "thread", "scope": SourceCoverageScope(object_ids=list(threads))})
        return request

    async def _project(self, payload: RetrievalPayload, request: Any) -> dict[str, Any]:
        ids = {str(item[key]) for records, keys in (
            (payload.l2_entity_cards, ("entity_id",)), (payload.l2_assertions, ("entity_id", "target_entity_id")),
            (payload.l2_relationships, ("subject_id", "object_id")))
            for item in records for key in keys if item.get(key)}
        ids.update(str(item["entity_id"]) for item in payload.trace.get("l2_query_trace", {}).get("resolved_entities", []) if item.get("entity_id"))
        if ids:
            names = (await self.resolve_names(ids) if self.resolve_names is not None
                     else await get_canonical_names(self.memory.memory_db_path, ids))
        else:
            names = {}
        return asdict(project_historical_recall(payload=payload, request=request,
            canonical_names=names, plugin_projection_service=self.projection))

    @staticmethod
    def _invalidated() -> dict[str, Any]:
        return {"status": "not_found", "findings": [], "summary": "Memory changed during retrieval; retry with current authority.",
                "answerability": "insufficient", "insufficient_evidence": True,
                "coverage": {"kind": "unknown", "can_claim_total": False},
                "answering_hints": {"must_not_claim_absence": True, "must_not_claim_current_state": True}}
