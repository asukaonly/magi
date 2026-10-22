"""Bounded source I/O with live connection and memory-governance checks."""
from __future__ import annotations

import asyncio
import inspect
import json
import time
from typing import Any

from magi_plugin_sdk.source_query import SourceQueryRequest, SourceQueryResult
from ...core.sqlite import sqlite_connection_async
from ...plugins.operation_execution import plugin_runtime_operation
from ..source_store import source_object_identity
from .policy import assess_coverage


async def check_cancellation(token: Any) -> None:
    if token is not None:
        cancelled = token.is_set() if isinstance(token, asyncio.Event) else token.is_cancelled()
        if inspect.isawaitable(cancelled):
            cancelled = await cancelled
        if cancelled:
            raise asyncio.CancelledError()


class SourceQueryExecutor:
    def __init__(self, *, registry: Any, store: Any, get_connection: Any, governance: Any) -> None:
        self.registry, self.store = registry, store
        self.get_connection, self.governance = get_connection, governance

    def admit(self, candidate: Any) -> Any:
        connection = self.get_connection(candidate.connection_id)
        if (connection is None or not connection.enabled or connection.plugin_id != candidate.plugin_id
                or connection != candidate.source.connection
                or self.registry.get_source(candidate.source_id) is not candidate.source):
            raise PermissionError("Source connection was disabled or replaced")
        spec = self.registry.get_spec(candidate.source_id)
        settings = connection.settings.get("sources", {}).get(candidate.source.source_type, {})
        if not settings.get("enabled", spec.metadata.get("default_settings", {}).get("enabled", True)):
            raise PermissionError("Source is disabled")
        if settings.get("allow_query", True) is not True:
            raise PermissionError("On-demand source queries are disabled")
        return connection

    async def _event_ids(self, candidate: Any, object_id: str) -> list[str]:
        await self.store.initialize()
        async with sqlite_connection_async(self.store.db_path) as db:
            rows = await db.execute_fetchall(
                "SELECT receipt_json FROM source_versions WHERE connection_id = ? AND source_id = ? "
                "AND object_id = ? AND receipt_json IS NOT NULL",
                (candidate.connection_id, candidate.source.source_id, object_id),
            )
        return [json.loads(row[0])["event_id"] for row in rows]

    async def run(self, candidate: Any, request: SourceQueryRequest, *, boundary: Any,
                  cancellation: Any, deadline: float, current: bool, max_pages: int = 3) -> tuple[list[dict], dict]:
        spec = self.registry.get_spec(candidate.source_id)
        caps = spec.query_capabilities
        if request.operation not in caps.operations or not set(request.fields) <= set(caps.fields):
            raise ValueError("Source does not support the requested read")
        if request.as_of is not None and not caps.supports_as_of:
            raise ValueError("Source cannot reconstruct historical state")
        request = request.model_copy(update={"limit": min(request.limit, caps.max_page_size)})
        started = time.time()
        seen_tokens: set[str] = set()
        findings: dict[str, dict] = {}
        omitted = False
        assessment: dict[str, Any] = {}
        async with plugin_runtime_operation():
            for page in range(max_pages):
                await check_cancellation(cancellation)
                connection = self.admit(candidate)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Source query budget exhausted")
                raw = await asyncio.wait_for(candidate.source.query_source(request), timeout=remaining)
                result = raw if isinstance(raw, SourceQueryResult) else SourceQueryResult.model_validate(raw)
                self.admit(candidate)
                await check_cancellation(cancellation)
                if len(result.items) > request.limit:
                    raise ValueError("Source exceeded the requested result bound")
                assessment = assess_coverage(result.coverage, request.scope, request.fields,
                    now=time.time(), current=current, require_checked_after=started if current else None)
                for item in result.items:
                    identity = source_object_identity(connection.connection_id, candidate.source.source_id, item.object_id)
                    event_ids = await self._event_ids(candidate, item.object_id)
                    visible = await self.governance.visible(boundary, source_type=candidate.source.source_type,
                        source_item_id=identity, occurred_at=item.occurred_at, event_ids=event_ids)
                    if not visible:
                        omitted = True
                        continue
                    if request.scope.object_ids and request.operation == "read" and item.object_id not in request.scope.object_ids:
                        raise ValueError("Source returned an object outside the requested scope")
                    if request.operation == "thread" and item.thread_id != request.scope.object_ids[0]:
                        raise ValueError("Source returned a message outside the requested thread")
                    if request.scope.start is not None and (item.occurred_at is None or item.occurred_at < request.scope.start):
                        omitted = True
                        continue
                    if request.scope.end is not None and (item.occurred_at is None or item.occurred_at >= request.scope.end):
                        omitted = True
                        continue
                    if not set(request.fields) <= set(item.fields):
                        omitted = True
                    findings[item.object_id] = {
                        "kind": "source_record", "statement": item.text, "title": item.title,
                        "origin": "source", "source_layer": "source", "source": candidate.source.source_type,
                        "occurred_at": item.occurred_at, "checked_at": result.coverage.checked_at,
                        "source_ref": {"identity": identity, "connection_id": connection.connection_id,
                            "source_id": candidate.source.source_id, "object_id": item.object_id,
                            "version": item.version, "thread_id": item.thread_id,
                            "provider": caps.provider, "account": connection.display_name},
                        "fields": item.fields, "metadata": item.metadata,
                        "url": item.url if item.url and item.url.startswith("https://") else None,
                    }
                token = result.next_page_token
                if not token:
                    break
                if token in seen_tokens:
                    raise ValueError("Source pagination made no progress")
                seen_tokens.add(token)
                request = request.model_copy(update={"page_token": token})
            if result.next_page_token or omitted:
                assessment.update(satisfied=False, complete=False,
                                  reason="governed_or_incomplete_evidence" if omitted else "page_budget_exhausted")
            # Recheck every returned identity after I/O, including concurrent forgets.
            for key, finding in list(findings.items()):
                if not await self.governance.visible(boundary, source_type=candidate.source.source_type,
                    source_item_id=finding["source_ref"]["identity"], occurred_at=finding["occurred_at"],
                    event_ids=await self._event_ids(candidate, key)):
                    findings.pop(key)
                    assessment.update(satisfied=False, complete=False, reason="governance_changed")
            self.admit(candidate)
            await check_cancellation(cancellation)
        assessment.update(connection_id=candidate.connection_id, provider=caps.provider,
                          scope=request.scope.model_dump(mode="json"), returned_count=len(findings))
        return list(findings.values()), assessment
