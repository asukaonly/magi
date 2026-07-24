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
from ..entities.catalog.lookup import get_canonical_names
from ..models import L2BatchJob, L2FocalEntityRef, L2HistoryContext
from ..store import L2CognitionStore

DEFAULT_L2_HISTORY_ENTITY_MATCH_LIMIT = 3
DEFAULT_L2_HISTORY_CONTEXT_LIMIT = 3
DEFAULT_L2_HISTORY_SEARCH_LIMIT = 4


def _context_row_precedes_event(row: dict[str, Any], event: MemoryEvent) -> bool:
    row_session_seq = row.get("session_seq")
    if event.session_id and event.session_seq is not None and row_session_seq is not None:
        return int(row_session_seq) < int(event.session_seq)

    row_timestamp = float(row.get("timestamp", 0.0) or 0.0)
    if row_timestamp != float(event.timestamp):
        return row_timestamp < float(event.timestamp)

    row_created_at = float(row.get("created_at", row_timestamp) or row_timestamp)
    if row_created_at != float(event.created_at):
        return row_created_at < float(event.created_at)

    row_id = row.get("id")
    if row_id is not None and event.id is not None:
        return int(row_id) < int(event.id)
    return False


def _context_row_order_key(row: dict[str, Any]) -> tuple[float, float, int, str]:
    session_seq = row.get("session_seq")
    return (
        float(session_seq) if session_seq is not None else float("-inf"),
        float(row.get("timestamp", 0.0) or 0.0),
        int(row.get("id", 0) or 0),
        str(row.get("event_id") or ""),
    )


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
            session_seq=(
                int(payload["session_seq"])
                if payload.get("session_seq") is not None
                else None
            ),
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
        messages = await self._load_context_messages(
            event,
            exclude_event_ids=exclude_event_ids,
        )
        return [str(message["content"]) for message in messages]

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

        context_limit = 3
        search_radius = max(4, len(exclude_event_ids or []) + 4)
        if event.session_id and event.session_seq is not None:
            rows = await host._l1_store.query_session_event_window(
                session_id=event.session_id,
                center_session_seq=event.session_seq,
                window=search_radius,
                user_id=event.user_id,
                limit=(search_radius * 2) + 1,
                include_metadata_json=False,
                include_embedding_fields=False,
            )
        elif event.user_id and _allows_user_context_fallback(event):
            rows = await host._l1_store.query_events(
                user_id=event.user_id,
                cognition_eligible=True,
                end_time=event.timestamp,
                limit=search_radius,
                include_metadata_json=False,
                include_embedding_fields=False,
                order_by="timestamp_desc",
            )
        else:
            return []

        excluded = set(exclude_event_ids or [])
        excluded.add(event.event_id)
        context_rows = [
            row
            for row in rows
            if str(row.get("event_id") or "") not in excluded
            and bool(row.get("cognition_eligible", True))
            and _context_row_precedes_event(row, event)
            and str(row.get("author_type") or "").strip().casefold()
            in {"assistant", "user"}
            and str(row.get("content") or "").strip()
        ]
        context_rows.sort(key=_context_row_order_key)
        context_rows = context_rows[-context_limit:]
        messages: list[dict[str, Any]] = []
        for row in context_rows:
            content = str(row.get("content", "")).strip()
            if not content:
                continue
            role = str(row.get("author_type", "user")).strip() or "user"
            messages.append(
                {
                    "event_id": str(row.get("event_id") or "").strip(),
                    "session_seq": row.get("session_seq"),
                    "timestamp": float(row.get("timestamp", 0.0) or 0.0),
                    "role": role,
                    "content": content,
                }
            )
        return messages

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

    async def _augment_event_window_with_entity_history(
        self,
        *,
        anchor_event: MemoryEvent,
        event_window: Any,
        focal_entities: list[L2FocalEntityRef],
        exclude_event_ids: list[str] | None = None,
    ) -> list[L2HistoryContext]:
        """Add L1 entity-linked history after Phase 1 has resolved entities."""
        linked_contexts = await self._load_entity_linked_history_contexts(
            anchor_event=anchor_event,
            focal_entities=focal_entities,
            exclude_event_ids=exclude_event_ids,
            existing_contexts=list(event_window.history_contexts or []),
        )
        if not linked_contexts:
            return list(event_window.history_contexts or [])

        merged_contexts = _merge_history_contexts(
            list(event_window.history_contexts or []) + linked_contexts
        )
        event_window.history_contexts = merged_contexts
        event_window.summary.history_context_count = len(merged_contexts)
        return merged_contexts

    async def _load_entity_linked_history_contexts(
        self,
        *,
        anchor_event: MemoryEvent,
        focal_entities: list[L2FocalEntityRef],
        exclude_event_ids: list[str] | None = None,
        existing_contexts: list[L2HistoryContext] | None = None,
    ) -> list[L2HistoryContext]:
        host = self._context_host()
        if host._l1_store is None or host._entity_catalog is None or not anchor_event.user_id:
            return []

        entity_ids = _history_entity_ids(focal_entities)
        if not entity_ids:
            return []

        excluded_event_ids = set(exclude_event_ids or [])
        excluded_event_ids.update(ctx.event_id for ctx in existing_contexts or [])
        linked_event_ids = await self._find_entity_linked_event_ids(
            entity_ids=entity_ids,
            exclude_event_ids=sorted(excluded_event_ids),
        )
        if not linked_event_ids:
            return []

        events = await host._l1_store.fetch_events(linked_event_ids, user_id=anchor_event.user_id)
        if not events:
            return []

        event_entities = await host._l1_store.get_event_entity_ids(
            [str(item.get("event_id") or "") for item in events]
        )
        canonical_names = await get_canonical_names(host._entity_catalog.db_path, entity_ids)
        return _entity_history_contexts_from_events(
            events=events,
            event_entities=event_entities,
            entity_ids=set(entity_ids),
            canonical_names=canonical_names,
            anchor_event=anchor_event,
            seen_event_ids=excluded_event_ids,
        )

    async def _find_entity_linked_event_ids(
        self,
        *,
        entity_ids: list[str],
        exclude_event_ids: list[str],
    ) -> list[str]:
        host = self._context_host()
        if host._l1_store is None:
            return []
        limit = min(
            12,
            max(
                DEFAULT_L2_HISTORY_CONTEXT_LIMIT,
                len(entity_ids) * DEFAULT_L2_HISTORY_SEARCH_LIMIT,
            ),
        )
        rows = await host._l1_store.find_events_by_entities(
            entity_ids,
            exclude_event_ids=exclude_event_ids,
            limit=limit,
        )
        return [event_id for event_id, _shared_count in rows]

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


def _allows_user_context_fallback(event: MemoryEvent) -> bool:
    return event.memory_domain in {MemoryDomain.USER_AUTHORED, MemoryDomain.INTERACTION}


def _history_entity_ids(focal_entities: list[L2FocalEntityRef]) -> list[str]:
    entity_ids: list[str] = []
    seen: set[str] = set()
    for entity in focal_entities:
        entity_id = str(getattr(entity, "entity_id", "") or "").strip()
        entity_type = str(getattr(entity, "entity_type", "") or "").strip().casefold()
        if not entity_id or entity_type == "user" or entity_id in seen:
            continue
        seen.add(entity_id)
        entity_ids.append(entity_id)
    return entity_ids


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


def _entity_history_contexts_from_events(
    *,
    events: list[dict[str, Any]],
    event_entities: dict[str, list[str]],
    entity_ids: set[str],
    canonical_names: dict[str, str],
    anchor_event: MemoryEvent,
    seen_event_ids: set[str],
) -> list[L2HistoryContext]:
    contexts: list[L2HistoryContext] = []
    for row in events:
        event_id = str(row.get("event_id") or "").strip()
        content = str(row.get("content") or "").strip()
        if not event_id or not content or event_id in seen_event_ids:
            continue
        if not bool(row.get("cognition_eligible", True)):
            continue
        if _same_session_as_anchor(row, anchor_event):
            continue
        matched_entity_id = _first_matching_entity_id(event_entities.get(event_id, []), entity_ids)
        if matched_entity_id is None:
            continue
        contexts.append(
            L2HistoryContext(
                event_id=event_id,
                session_id=str(row.get("session_id") or "").strip() or None,
                timestamp=float(row.get("timestamp", 0.0) or 0.0),
                content=content,
                matched_entity_id=matched_entity_id,
                matched_text=canonical_names.get(matched_entity_id, matched_entity_id),
                canonical_name=canonical_names.get(matched_entity_id),
                match_source="l1_event_entities",
            )
        )
    return contexts


def _first_matching_entity_id(event_entity_ids: list[str], entity_ids: set[str]) -> str | None:
    for entity_id in event_entity_ids:
        if entity_id in entity_ids:
            return entity_id
    return None


def _same_session_as_anchor(row: dict[str, Any], anchor_event: MemoryEvent) -> bool:
    return bool(
        anchor_event.session_id and str(row.get("session_id") or "") == anchor_event.session_id
    )


def _merge_history_contexts(contexts: Iterable[L2HistoryContext]) -> list[L2HistoryContext]:
    merged: dict[str, L2HistoryContext] = {}
    for context in contexts:
        _keep_newer_history_context(merged, context)
    return _select_history_contexts(merged.values())


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
        key=lambda item: (
            1 if item.match_source == "l1_event_entities" else 0,
            float(item.timestamp),
            str(item.event_id),
        ),
        reverse=True,
    )
    selected_contexts = ranked_contexts[:DEFAULT_L2_HISTORY_CONTEXT_LIMIT]
    return sorted(
        selected_contexts,
        key=lambda item: (float(item.timestamp), str(item.event_id)),
    )
