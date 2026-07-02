"""Context loading helpers for the L2 cognition pipeline."""

from __future__ import annotations

import time
from typing import Any, Iterable, Optional, Protocol, cast

from ...event_contracts import (
    IngestTarget,
    MemoryDomain,
    MemoryEvent,
    RetentionClass,
    TomDepth,
)
from ...l1.event_store import L1EventStore
from ..context_bundle import ContextBundle, ResolvedContextRef
from ..context_collector import collect_context_bundle
from ..entities.catalog import L2EntityCatalog
from ..models import L2BatchJob, L2FocalEntityRef, L2HistoryContext
from ..store import L2CognitionStore

DEFAULT_L2_HISTORY_ENTITY_MATCH_LIMIT = 3
DEFAULT_L2_HISTORY_CONTEXT_LIMIT = 3
DEFAULT_L2_HISTORY_SEARCH_LIMIT = 4


class _L2PipelineContextHostProtocol(Protocol):
    _l1_store: L1EventStore | None
    _entity_catalog: L2EntityCatalog | None
    _cognition_store: L2CognitionStore | None

    def _non_empty_text(self, value: Any) -> Optional[str]: ...


class L2PipelineContextMixin:
    """Own context retrieval, event hydration, and resolved-context merging."""

    async def _load_stored_event(self, event: MemoryEvent) -> MemoryEvent:
        host = self._context_host()
        if host._l1_store is None:
            return event
        stored_event = await host._l1_store.get_memory_event(event.event_id)
        if stored_event is None:
            return event
        return stored_event

    async def _load_batch_events(self, job: L2BatchJob) -> list[MemoryEvent]:
        batch_events: list[MemoryEvent] = []
        for payload in job.events:
            event = self._deserialize_batch_event(payload)
            if event is None:
                continue
            batch_events.append(await self._load_stored_event(event))
        return batch_events

    def _deserialize_batch_event(self, payload: dict[str, Any]) -> MemoryEvent | None:
        host = self._context_host()
        if not isinstance(payload, dict):
            return None
        event_id = host._non_empty_text(payload.get("event_id"))
        if event_id is None:
            return None
        return MemoryEvent(
            event_id=event_id,
            correlation_id=str(payload.get("correlation_id") or ""),
            timestamp=float(payload.get("timestamp", 0.0) or 0.0),
            created_at=float(payload.get("created_at", payload.get("timestamp", 0.0)) or 0.0),
            event_type=str(payload.get("event_type") or ""),
            source=str(payload.get("source") or "unknown"),
            source_item_id=host._non_empty_text(payload.get("source_item_id")),
            memory_domain=MemoryDomain.from_value(payload.get("memory_domain", "user_authored")),
            ingest_target=IngestTarget.from_value(payload.get("ingest_target", "l1_only")),
            cognition_eligible=bool(payload.get("cognition_eligible", True)),
            tom_depth=TomDepth.from_value(payload.get("tom_depth", "topology_only")),
            retention_class=RetentionClass.from_value(
                payload.get("retention_class", "compressible")
            ),
            session_id=host._non_empty_text(payload.get("session_id")),
            turn_id=host._non_empty_text(payload.get("turn_id")),
            user_id=host._non_empty_text(payload.get("user_id")),
            task_id=host._non_empty_text(payload.get("task_id")),
            content=str(payload.get("content") or ""),
            author_type=str(payload.get("author_type") or "user"),
            content_type=str(payload.get("content_type") or "text"),
            importance_score=float(payload.get("importance_score", 0.5) or 0.5),
            level=int(payload.get("level", 1) or 1),
            media_path=host._non_empty_text(payload.get("media_path")),
        )

    async def _load_context_texts(
        self, event: MemoryEvent, *, exclude_event_ids: list[str] | None = None
    ) -> list[str]:
        host = self._context_host()
        if host._l1_store is None:
            return []

        query_args: dict[str, Any] = {
            "cognition_eligible": True,
            "limit": max(4, len(exclude_event_ids or []) + 4),
        }
        if event.session_id:
            query_args["session_id"] = event.session_id
        elif event.user_id:
            query_args["user_id"] = event.user_id
        else:
            return []

        rows = await host._l1_store.query_events(**query_args)
        excluded = set(exclude_event_ids or [])
        excluded.add(event.event_id)
        context_rows = [row for row in rows if row["event_id"] not in excluded]
        context_texts = [
            str(row["content"]) for row in reversed(context_rows) if str(row["content"]).strip()
        ]
        return context_texts[:3]

    async def _load_context_messages(
        self,
        event: MemoryEvent,
        *,
        exclude_event_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Load recent context messages with author_type role annotation."""
        host = self._context_host()
        if host._l1_store is None:
            return []

        query_args: dict[str, Any] = {
            "cognition_eligible": True,
            "limit": max(4, len(exclude_event_ids or []) + 4),
        }
        if event.session_id:
            query_args["session_id"] = event.session_id
        elif event.user_id:
            query_args["user_id"] = event.user_id
        else:
            return []

        rows = await host._l1_store.query_events(**query_args)
        excluded = set(exclude_event_ids or [])
        excluded.add(event.event_id)
        context_rows = [row for row in rows if row["event_id"] not in excluded]
        messages: list[dict[str, Any]] = []
        for row in reversed(context_rows):
            content = str(row.get("content", "")).strip()
            if not content:
                continue
            role = str(row.get("author_type", "user")).strip() or "user"
            messages.append({"role": role, "content": content})
        return messages[:3]

    async def _load_existing_graph_context(
        self,
        focal_entities: list[L2FocalEntityRef],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Load existing graph edges and assertions for focal entities."""
        host = self._context_host()
        if host._cognition_store is None:
            return [], []

        graph_edges: list[dict[str, Any]] = []
        assertions: list[dict[str, Any]] = []
        seen_triple_ids: set[str] = set()
        seen_assertion_ids: set[str] = set()

        for entity in focal_entities:
            for relations in [
                await host._cognition_store.get_relationships(
                    subject_id=entity.entity_id, limit=30
                ),
                await host._cognition_store.get_relationships(object_id=entity.entity_id, limit=30),
            ]:
                for relation in relations:
                    triple_id = str(relation.get("triple_id", ""))
                    if triple_id in seen_triple_ids:
                        continue
                    seen_triple_ids.add(triple_id)
                    graph_edges.append(relation)

            entity_assertions = await host._cognition_store.list_tom_assertions(
                entity_id=entity.entity_id,
                entity_type=entity.entity_type,
                limit=20,
            )
            for assertion in entity_assertions:
                assertion_id = str(assertion.get("assertion_id", ""))
                if assertion_id in seen_assertion_ids:
                    continue
                seen_assertion_ids.add(assertion_id)
                assertions.append(assertion)

        return graph_edges[:30], assertions[:20]

    async def _load_history_contexts(
        self,
        *,
        anchor_event: MemoryEvent,
        batch_events: list[MemoryEvent],
        exclude_event_ids: list[str] | None = None,
    ) -> list[L2HistoryContext]:
        host = self._context_host()
        if host._l1_store is None or host._entity_catalog is None or not anchor_event.user_id:
            return []

        query_text = " ".join(
            text for event in batch_events if (text := host._non_empty_text(event.content))
        ).strip()
        if not query_text:
            return []

        entity_matches = await self._resolve_history_entity_matches(host, query_text)
        if not entity_matches:
            return []

        matches_by_event_id = await self._search_history_contexts_for_entities(
            host=host,
            anchor_event=anchor_event,
            entity_matches=entity_matches,
            exclude_event_ids=exclude_event_ids,
        )
        return _select_history_contexts(matches_by_event_id.values())

    async def _resolve_history_entity_matches(
        self, host: _L2PipelineContextHostProtocol, query_text: str
    ) -> list[dict[str, Any]]:
        if host._entity_catalog is None:
            return []
        return cast(
            list[dict[str, Any]],
            await host._entity_catalog.resolve_query_entities(
                query_text,
                limit=DEFAULT_L2_HISTORY_ENTITY_MATCH_LIMIT,
            ),
        )

    async def _search_history_contexts_for_entities(
        self,
        *,
        host: _L2PipelineContextHostProtocol,
        anchor_event: MemoryEvent,
        entity_matches: list[dict[str, Any]],
        exclude_event_ids: list[str] | None,
    ) -> dict[str, L2HistoryContext]:
        seen_event_ids = set(exclude_event_ids or [])
        seen_terms: set[str] = set()
        matches_by_event_id: dict[str, L2HistoryContext] = {}
        for match in entity_matches:
            for term in _history_match_terms(match, host):
                if _already_seen_history_term(term, seen_terms):
                    continue
                await self._merge_history_term_matches(
                    host=host,
                    anchor_event=anchor_event,
                    match=match,
                    term=term,
                    seen_event_ids=seen_event_ids,
                    matches_by_event_id=matches_by_event_id,
                )
        return matches_by_event_id

    async def _merge_history_term_matches(
        self,
        *,
        host: _L2PipelineContextHostProtocol,
        anchor_event: MemoryEvent,
        match: dict[str, Any],
        term: str,
        seen_event_ids: set[str],
        matches_by_event_id: dict[str, L2HistoryContext],
    ) -> None:
        if host._l1_store is None:
            return
        rows = await host._l1_store.search_events(
            query=term,
            user_id=anchor_event.user_id,
            limit=DEFAULT_L2_HISTORY_SEARCH_LIMIT,
        )
        for row in rows:
            history_context = _history_context_from_row(
                host=host,
                row=row,
                match=match,
                term=term,
                anchor_event=anchor_event,
                seen_event_ids=seen_event_ids,
            )
            if history_context is None:
                continue
            _keep_newer_history_context(matches_by_event_id, history_context)
            seen_event_ids.add(history_context.event_id)

    async def _collect_context_bundle(
        self,
        event: MemoryEvent,
        *,
        context_texts: list[str],
        source_event_ids: list[str] | None = None,
    ) -> ContextBundle:
        host = self._context_host()
        recent_entities: list[dict[str, Any]] = []
        if host._entity_catalog is not None:
            recent_entities = await host._entity_catalog.list_mentions(limit=20)
        return collect_context_bundle(
            event=event,
            recent_messages=[{"text": text} for text in context_texts if text],
            recent_entities=recent_entities,
            source_event_ids=list(source_event_ids or []),
        )

    def _merge_resolved_context_refs(
        self,
        *,
        direct_refs: list[Any],
        llm_refs: list[ResolvedContextRef],
        context_bundle: ContextBundle,
    ) -> list[ResolvedContextRef]:
        host = self._context_host()
        allowed_refs = {
            item.context_id: item.kind
            for item in context_bundle.live_context_entities
            if item.expires_at is None or item.expires_at > time.time()
        }
        merged: dict[str, ResolvedContextRef] = {}
        for ref in direct_refs:
            if isinstance(ref, ResolvedContextRef):
                merged[ref.surface] = ref
                continue
            payload = ref.to_dict() if hasattr(ref, "to_dict") else dict(ref)
            surface = host._non_empty_text(payload.get("surface"))
            if not surface:
                continue
            merged[surface] = ResolvedContextRef(
                surface=surface,
                reference_type=host._non_empty_text(payload.get("reference_type")) or "unresolved",
                resolved_ref=host._non_empty_text(payload.get("resolved_ref")) or "",
                resolved_kind=host._non_empty_text(payload.get("resolved_kind")) or "",
                confidence=float(payload.get("confidence", 0.0) or 0.0),
                evidence_text=host._non_empty_text(payload.get("evidence_text")) or "",
            )
        for ref in llm_refs:
            if not isinstance(ref, ResolvedContextRef) or not ref.surface:
                continue
            if ref.reference_type == "context_entity":
                if not ref.resolved_ref or ref.resolved_ref not in allowed_refs:
                    continue
            merged[ref.surface] = ref
        return list(merged.values())

    def _context_host(self) -> _L2PipelineContextHostProtocol:
        return self  # type: ignore[return-value]


def _history_match_terms(match: dict[str, Any], host: _L2PipelineContextHostProtocol) -> list[str]:
    candidate_terms = [
        host._non_empty_text(match.get("matched_text")),
        host._non_empty_text(match.get("canonical_name")),
    ]
    return [term for term in candidate_terms if term is not None]


def _already_seen_history_term(term: str, seen_terms: set[str]) -> bool:
    normalized_term = term.casefold()
    if normalized_term in seen_terms:
        return True
    seen_terms.add(normalized_term)
    return False


def _history_context_from_row(
    *,
    host: _L2PipelineContextHostProtocol,
    row: dict[str, Any],
    match: dict[str, Any],
    term: str,
    anchor_event: MemoryEvent,
    seen_event_ids: set[str],
) -> L2HistoryContext | None:
    event_id = host._non_empty_text(row.get("event_id"))
    content = host._non_empty_text(row.get("content"))
    if not event_id or not content or event_id in seen_event_ids:
        return None
    if not bool(row.get("cognition_eligible", True)):
        return None
    if _same_session_as_anchor(row, anchor_event):
        return None
    return L2HistoryContext(
        event_id=event_id,
        session_id=host._non_empty_text(row.get("session_id")),
        timestamp=float(row.get("timestamp", 0.0) or 0.0),
        content=content,
        matched_entity_id=host._non_empty_text(match.get("entity_id")),
        matched_text=term,
        canonical_name=host._non_empty_text(match.get("canonical_name")),
        match_source=host._non_empty_text(match.get("match_source")),
    )


def _same_session_as_anchor(row: dict[str, Any], anchor_event: MemoryEvent) -> bool:
    return bool(
        anchor_event.session_id and str(row.get("session_id") or "") == anchor_event.session_id
    )


def _keep_newer_history_context(
    matches_by_event_id: dict[str, L2HistoryContext],
    history_context: L2HistoryContext,
) -> None:
    existing_context = matches_by_event_id.get(history_context.event_id)
    if existing_context is None or history_context.timestamp > existing_context.timestamp:
        matches_by_event_id[history_context.event_id] = history_context


def _select_history_contexts(
    contexts: Iterable[L2HistoryContext],
) -> list[L2HistoryContext]:
    ranked_contexts = sorted(
        contexts,
        key=lambda item: (float(item.timestamp), str(item.event_id)),
        reverse=True,
    )
    selected_contexts = ranked_contexts[:DEFAULT_L2_HISTORY_CONTEXT_LIMIT]
    return sorted(
        selected_contexts,
        key=lambda item: (float(item.timestamp), str(item.event_id)),
    )
