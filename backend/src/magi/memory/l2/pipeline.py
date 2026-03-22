"""Asynchronous queue workers for L2 cognition processing."""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable, Optional

from ...core.logger import get_logger
from ..event_contracts import MemoryEvent
from ..l1.event_store import L1EventStore
from .context_bundle import ContextBundle, ContextEntity
from .context_collector import collect_context_bundle, resolve_direct_context_refs
from .store import L2CognitionStore
from .evidence_classifier import classify_event_evidence
from .evidence_policy import resolve_l2_policy
from .entity_catalog import L2EntityCatalog
from .extraction_profiles import ExtractionProfile, resolve_extraction_profile
from .llm_service import L2LLMService
from .ontology import (
    coerce_unknown_entity_type,
    is_leaf_fact_duplicate,
    validate_assertion_candidate,
    validate_graph_candidate,
)

_POSITIVE_PREFERENCE_MARKERS = (" like ", " likes ", "喜欢", "love ", "loves ")
_NEGATIVE_PREFERENCE_MARKERS = (" dislike ", " dislikes ", "不喜欢", "do not like", "don't like")
_TOPOLOGY_ONLY_TRAIT_FAMILIES = {"public_sentiment", "group_atmosphere", "relationship_shift"}
_GRAPH_ELIGIBLE_ENTITY_TYPES = {
    "place",
    "person",
    "organization",
    "group",
    "product",
    "food",
    "topic",
    "event",
    "media",
    "other",
}
logger = get_logger(__name__)
DEFAULT_L2_EXTRACT_WORKER_COUNT = 5


@dataclass(slots=True)
class L2PipelineStats:
    """Counters for the staged L2 background pipeline."""

    is_running: bool = False
    extract_enqueued: int = 0
    extract_completed: int = 0
    extract_failed: int = 0
    extract_skipped: int = 0
    reconcile_enqueued: int = 0
    reconcile_completed: int = 0
    reconcile_failed: int = 0
    snapshot_enqueued: int = 0
    snapshot_completed: int = 0
    snapshot_failed: int = 0
    relations_written: int = 0
    assertions_written: int = 0
    extract_by_evidence_class: dict[str, int] = field(default_factory=dict)
    skip_by_reason: dict[str, int] = field(default_factory=dict)


class L2Pipeline:
    """Owns asynchronous L2 extraction and follow-up queues."""

    def __init__(
        self,
        cognition_store: Optional[L2CognitionStore],
        *,
        l1_store: Optional[L1EventStore] = None,
        entity_catalog: Optional[L2EntityCatalog] = None,
        llm_service: Optional[L2LLMService] = None,
        state_change_callback: Callable[[str, str, list[dict[str, Any]]], Awaitable[None]] | None = None,
        batch_flush_interval_seconds: int = 60,
    ) -> None:
        self._cognition_store = cognition_store
        self._l1_store = l1_store
        self._entity_catalog = entity_catalog
        self._llm_service = llm_service
        self._state_change_callback = state_change_callback
        self._batch_flush_interval_seconds = max(30, int(batch_flush_interval_seconds))
        self._extract_queue: asyncio.Queue[MemoryEvent | None] = asyncio.Queue()
        self._reconcile_queue: asyncio.Queue[list[str] | None] = asyncio.Queue()
        self._snapshot_queue: asyncio.Queue[list[str] | None] = asyncio.Queue()
        self._extract_worker_count = DEFAULT_L2_EXTRACT_WORKER_COUNT
        self._extract_workers: list[asyncio.Task[None]] = []
        self._extract_worker: asyncio.Task[None] | None = None
        self._reconcile_worker: asyncio.Task[None] | None = None
        self._snapshot_worker: asyncio.Task[None] | None = None
        self._stats = L2PipelineStats()

    async def start(self) -> None:
        if self._stats.is_running or self._cognition_store is None:
            return

        self._stats.is_running = True
        self._extract_workers = [asyncio.create_task(self._run_extract_worker()) for _ in range(self._extract_worker_count)]
        self._extract_worker = self._extract_workers[0] if self._extract_workers else None
        self._reconcile_worker = asyncio.create_task(self._run_reconcile_worker())
        self._snapshot_worker = asyncio.create_task(self._run_snapshot_worker())

    async def shutdown(self) -> None:
        if not self._stats.is_running:
            return

        self._stats.is_running = False
        for _ in range(self._extract_worker_count):
            await self._extract_queue.put(None)
        await self._reconcile_queue.put(None)
        await self._snapshot_queue.put(None)

        for worker in [*self._extract_workers, self._reconcile_worker, self._snapshot_worker]:
            if worker is None:
                continue
            try:
                await worker
            except asyncio.CancelledError:
                pass

        self._extract_workers = []
        self._extract_worker = None
        self._reconcile_worker = None
        self._snapshot_worker = None

    async def enqueue_event(self, event: MemoryEvent) -> bool:
        if self._cognition_store is None or not event.cognition_eligible:
            self._stats.extract_skipped += 1
            return False

        await self._extract_queue.put(event)
        self._stats.extract_enqueued += 1
        return True

    async def enqueue_entities(self, entity_ids: list[str]) -> bool:
        normalized = sorted({entity_id.strip() for entity_id in entity_ids if entity_id and entity_id.strip()})
        if not normalized or self._cognition_store is None:
            return False
        await self._reconcile_queue.put(normalized)
        self._stats.reconcile_enqueued += 1
        return True

    async def enqueue_snapshot_refresh(self, entity_ids: list[str]) -> bool:
        normalized = sorted({entity_id.strip() for entity_id in entity_ids if entity_id and entity_id.strip()})
        if not normalized or self._cognition_store is None:
            return False
        await self._snapshot_queue.put(normalized)
        self._stats.snapshot_enqueued += 1
        return True

    def get_statistics(self) -> dict[str, int | bool]:
        return asdict(self._stats)

    async def _run_extract_worker(self) -> None:
        if self._cognition_store is None:
            return

        while True:
            event = await self._extract_queue.get()
            try:
                if event is None:
                    break
                logger.info(
                    "L2 extract started",
                    event_id=event.event_id,
                    event_type=event.event_type,
                    source=event.source,
                    queue_size=self._extract_queue.qsize(),
                )
                result = await self._extract_and_persist(event)
                self._stats.extract_completed += 1
                if result.get("skipped"):
                    self._stats.extract_skipped += 1
                    logger.info(
                        "L2 extract skipped",
                        event_id=event.event_id,
                        evidence_class=result.get("evidence_class"),
                        skip_reason=result.get("skip_reason"),
                        queue_size=self._extract_queue.qsize(),
                    )
                else:
                    logger.info(
                        "L2 extract completed",
                        event_id=event.event_id,
                        evidence_class=result.get("evidence_class"),
                        profile_id=result.get("profile_id"),
                        mention_count=int(result.get("mention_count", 0)),
                        graph_candidate_count=int(result.get("graph_candidate_count", 0)),
                        assertion_candidate_count=int(result.get("assertion_candidate_count", 0)),
                        rejected_graph_candidate_count=int(result.get("rejected_graph_candidate_count", 0)),
                        rejected_assertion_candidate_count=int(result.get("rejected_assertion_candidate_count", 0)),
                        relation_count=int(result["relation_count"]),
                        assertion_count=int(result["assertion_count"]),
                        contradiction_hint_count=int(result.get("contradiction_hint_count", 0)),
                        touched_entity_count=len(result.get("touched_entity_ids", [])),
                        queue_size=self._extract_queue.qsize(),
                    )
                self._stats.relations_written += int(result["relation_count"])
                self._stats.assertions_written += int(result["assertion_count"])
                touched_entity_ids = result.get("touched_entity_ids", [])
                if isinstance(touched_entity_ids, list) and touched_entity_ids:
                    await self.enqueue_entities(touched_entity_ids)
            except Exception:
                self._stats.extract_failed += 1
                logger.exception(
                    "L2 extract failed",
                    event_id=getattr(event, "event_id", None),
                    queue_size=self._extract_queue.qsize(),
                )
            finally:
                self._extract_queue.task_done()

    async def _run_reconcile_worker(self) -> None:
        while True:
            entity_ids = await self._reconcile_queue.get()
            try:
                if entity_ids is None:
                    break
                logger.info(
                    "L2 reconcile started",
                    entity_ids=entity_ids,
                    queue_size=self._reconcile_queue.qsize(),
                )
                snapshot_candidates: set[str] = set()
                total_outcomes = 0
                if self._cognition_store is not None:
                    for entity_id in entity_ids:
                        outcomes = await self._cognition_store.reconcile_entity(
                            entity_id=entity_id,
                            entity_type=self._entity_type_from_id(entity_id),
                            evidence_timestamps=await self._load_evidence_timestamps(entity_id),
                        )
                        total_outcomes += len(outcomes)
                        if outcomes:
                            snapshot_candidates.add(entity_id)
                            await self._emit_state_change_insight(
                                entity_id=entity_id,
                                entity_type=self._entity_type_from_id(entity_id),
                                outcomes=outcomes,
                            )
                if snapshot_candidates:
                    await self.enqueue_snapshot_refresh(sorted(snapshot_candidates))
                self._stats.reconcile_completed += 1
                logger.info(
                    "L2 reconcile completed",
                    entity_ids=entity_ids,
                    outcome_count=total_outcomes,
                    snapshot_candidate_count=len(snapshot_candidates),
                    queue_size=self._reconcile_queue.qsize(),
                )
            except Exception:
                self._stats.reconcile_failed += 1
                logger.exception(
                    "L2 reconcile failed",
                    entity_ids=entity_ids,
                    queue_size=self._reconcile_queue.qsize(),
                )
            finally:
                self._reconcile_queue.task_done()

    async def _emit_state_change_insight(
        self,
        *,
        entity_id: str,
        entity_type: str,
        outcomes: list[dict[str, Any]],
    ) -> None:
        if self._state_change_callback is None or not outcomes:
            return
        try:
            await self._state_change_callback(entity_id, entity_type, outcomes)
        except Exception:
            logger.exception(
                "L2 state change insight callback failed",
                entity_id=entity_id,
                entity_type=entity_type,
                outcome_count=len(outcomes),
            )

    async def _run_snapshot_worker(self) -> None:
        while True:
            entity_ids = await self._snapshot_queue.get()
            try:
                if entity_ids is None:
                    break
                logger.info(
                    "L2 snapshot started",
                    entity_ids=entity_ids,
                    queue_size=self._snapshot_queue.qsize(),
                )
                refreshed_count = 0
                if self._cognition_store is not None:
                    for entity_id in entity_ids:
                        snapshot = await self._cognition_store.refresh_entity_snapshot(
                            entity_id=entity_id,
                            entity_type=self._entity_type_from_id(entity_id),
                        )
                        if snapshot is not None:
                            refreshed_count += 1
                self._stats.snapshot_completed += 1
                logger.info(
                    "L2 snapshot completed",
                    entity_ids=entity_ids,
                    refreshed_count=refreshed_count,
                    queue_size=self._snapshot_queue.qsize(),
                )
            except Exception:
                self._stats.snapshot_failed += 1
                logger.exception(
                    "L2 snapshot failed",
                    entity_ids=entity_ids,
                    queue_size=self._snapshot_queue.qsize(),
                )
            finally:
                self._snapshot_queue.task_done()

    async def _extract_and_persist(self, event: MemoryEvent) -> dict[str, Any]:
        if self._cognition_store is None:
            return {"relation_count": 0, "assertion_count": 0, "touched_entity_ids": [], "skipped": True}

        stored_event = await self._load_stored_event(event)
        classification = classify_event_evidence(stored_event)
        self._increment_bucket(self._stats.extract_by_evidence_class, classification.evidence_class)
        logger.debug(
            "L2 evidence classified",
            event_id=stored_event.event_id,
            evidence_class=classification.evidence_class,
            grounding_type=classification.grounding_type,
            semantic_owner=classification.semantic_owner,
            originality_type=classification.originality_type,
            source_event_ids=classification.source_event_ids,
        )
        policy = resolve_l2_policy(classification)
        logger.debug(
            "L2 policy resolved",
            event_id=stored_event.event_id,
            evidence_class=classification.evidence_class,
            allow_entity_extraction=policy.allow_entity_extraction,
            allow_graph_write=policy.allow_graph_write,
            allow_assertion_write=policy.allow_assertion_write,
            allow_snapshot_impact=policy.allow_snapshot_impact,
            graph_scope=policy.graph_scope,
            assertion_scope=policy.assertion_scope,
            skip_reason=policy.skip_reason,
        )
        if not policy.allow_graph_write and not policy.allow_assertion_write:
            if policy.skip_reason:
                self._increment_bucket(self._stats.skip_by_reason, policy.skip_reason)
            return {
                "relation_count": 0,
                "assertion_count": 0,
                "touched_entity_ids": [],
                "skipped": True,
                "skip_reason": policy.skip_reason,
                "evidence_class": classification.evidence_class,
                "contradiction_hint_count": 0,
            }

        if self._entity_catalog is None or self._llm_service is None:
            legacy_result = await self._cognition_store.apply_memory_event(stored_event)
            return {
                **legacy_result,
                "touched_entity_ids": self._collect_touched_entities([], []),
                "skipped": False,
                "evidence_class": classification.evidence_class,
                "contradiction_hint_count": 0,
            }

        context_texts = (
            await self._load_context_texts(stored_event)
            if policy.allow_entity_extraction or policy.allow_assertion_write or policy.allow_graph_write
            else []
        )
        extraction_profile = resolve_extraction_profile(stored_event)
        self_entity_id = self._resolve_self_entity_id(stored_event)
        context_bundle = await self._collect_context_bundle(stored_event, context_texts=context_texts)
        direct_context_refs = resolve_direct_context_refs(event=stored_event, bundle=context_bundle)
        logger.info(
            "L2 unified extraction stage started",
            event_id=stored_event.event_id,
            profile_id=extraction_profile.profile_id,
            context_count=len(context_texts),
            structured_entity_hint_count=0,
            structured_graph_hint_count=0,
            direct_context_ref_count=len(direct_context_refs),
            live_context_candidate_count=len(context_bundle.live_context_entities),
        )
        unified_result = await self._llm_service.extract_unified_candidates(
            event_window={
                "event_ids": [stored_event.event_id],
                "texts": [stored_event.content],
                "context_texts": context_texts,
            },
            profile=extraction_profile,
            focal_subject={
                "entity_ref": self_entity_id,
                "entity_type": "user" if self_entity_id else None,
            },
            context_bundle=context_bundle,
        )
        resolved_context_refs = self._merge_resolved_context_refs(
            direct_refs=direct_context_refs,
            llm_refs=list(unified_result.get("resolved_context_refs", [])),
            context_bundle=context_bundle,
        )

        raw_mentions = list(unified_result.get("mentions", []))
        resolved_mentions: list[dict[str, Any]] = []
        if policy.allow_entity_extraction:
            resolved_mentions = await self._resolve_mentions(stored_event, raw_mentions)
            logger.debug(
                "L2 mentions resolved",
                event_id=stored_event.event_id,
                profile_id=extraction_profile.profile_id,
                mention_count=len(raw_mentions),
                resolved_mention_count=len(resolved_mentions),
            )

        graph_candidates, rejected_graph_candidate_count = self._prepare_unified_graph_candidates(
            event=stored_event,
            profile=extraction_profile,
            policy=policy,
            resolved_mentions=resolved_mentions,
            resolved_context_refs=resolved_context_refs,
            raw_candidates=(
                list(unified_result.get("graph_candidates", []))
            ),
        )
        if policy.allow_graph_write and policy.graph_scope == "full" and not graph_candidates:
            graph_candidates = self._build_graph_candidates(stored_event, resolved_mentions)
            if not graph_candidates:
                graph_candidates = self._cognition_store.extract_graph_candidates(stored_event)

        focal_entities = self._build_focal_entities(stored_event, resolved_mentions)
        assertion_candidates, rejected_assertion_candidate_count = self._prepare_unified_assertion_candidates(
            event=stored_event,
            profile=extraction_profile,
            policy=policy,
            graph_candidates=graph_candidates,
            resolved_context_refs=resolved_context_refs,
            raw_candidates=list(unified_result.get("assertion_candidates", [])),
        )
        if policy.allow_assertion_write and not assertion_candidates and policy.assertion_scope == "full":
            assertion_candidates = self._cognition_store.extract_assertion_candidates(stored_event)
        logger.debug(
            "L2 candidates built",
            event_id=stored_event.event_id,
            profile_id=extraction_profile.profile_id,
            graph_candidate_count=len(graph_candidates),
            assertion_candidate_count=len(assertion_candidates),
            focal_entity_count=len(focal_entities),
            resolved_context_ref_count=len(resolved_context_refs),
        )
        logger.info(
            "L2 unified candidate validation completed",
            event_id=stored_event.event_id,
            profile_id=extraction_profile.profile_id,
            mention_count=len(raw_mentions),
            graph_candidate_count=len(graph_candidates),
            assertion_candidate_count=len(assertion_candidates),
            rejected_graph_candidate_count=rejected_graph_candidate_count,
            rejected_assertion_candidate_count=rejected_assertion_candidate_count,
        )

        contradiction_hints = []
        if policy.count_as_new_evidence and (graph_candidates or assertion_candidates):
            contradiction_hints = await self._detect_contradiction_hints(
                event=stored_event,
                focal_entities=focal_entities,
            )
            logger.debug(
                "L2 contradiction hints detected",
                event_id=stored_event.event_id,
                contradiction_hint_count=len(contradiction_hints),
            )

        relation_count = 0
        assertion_count = 0
        for candidate in graph_candidates:
            await self._cognition_store.upsert_knowledge_edge(**candidate)
            relation_count += 1

        for candidate in assertion_candidates:
            await self._cognition_store.upsert_assertion_candidate(candidate)
            assertion_count += 1

        for hint in contradiction_hints:
            await self._cognition_store.apply_contradiction_hint(hint)

        logger.info(
            "L2 persistence completed",
            event_id=stored_event.event_id,
            profile_id=extraction_profile.profile_id,
            relation_count=relation_count,
            assertion_count=assertion_count,
            contradiction_hint_count=len(contradiction_hints),
        )

        return {
            "relation_count": relation_count,
            "assertion_count": assertion_count,
            "touched_entity_ids": self._collect_touched_entities(graph_candidates, assertion_candidates),
            "skipped": False,
            "evidence_class": classification.evidence_class,
            "profile_id": extraction_profile.profile_id,
            "mention_count": len(raw_mentions),
            "resolved_context_ref_count": len(resolved_context_refs),
            "graph_candidate_count": len(graph_candidates),
            "assertion_candidate_count": len(assertion_candidates),
            "rejected_graph_candidate_count": rejected_graph_candidate_count,
            "rejected_assertion_candidate_count": rejected_assertion_candidate_count,
            "contradiction_hint_count": len(contradiction_hints),
        }

    async def _load_stored_event(self, event: MemoryEvent) -> MemoryEvent:
        if self._l1_store is None:
            return event
        stored_event = await self._l1_store.get_memory_event(event.event_id)
        if stored_event is None:
            return event
        return stored_event

    async def _load_context_texts(self, event: MemoryEvent) -> list[str]:
        if self._l1_store is None:
            return []

        query_args: dict[str, Any] = {"cognition_eligible": True, "limit": 4}
        if event.session_id:
            query_args["session_id"] = event.session_id
        elif event.user_id:
            query_args["user_id"] = event.user_id
        else:
            return []

        rows = await self._l1_store.query_events(**query_args)
        context_rows = [row for row in rows if row["event_id"] != event.event_id]
        context_texts = [str(row["content"]) for row in reversed(context_rows) if str(row["content"]).strip()]
        return context_texts[:3]

    async def _resolve_mentions(
        self,
        event: MemoryEvent,
        mentions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if self._entity_catalog is None:
            return []

        resolved_mentions: list[dict[str, Any]] = []
        for mention in mentions:
            if not isinstance(mention, dict):
                continue

            mention_text = str(mention.get("mention_text", "")).strip()
            if not mention_text:
                continue
            normalized_surface = str(mention.get("normalized_surface") or mention_text).strip()
            entity_type = self._normalize_entity_type(mention.get("entity_type"))
            evidence_text = self._non_empty_text(mention.get("evidence_text")) or event.content
            mention_confidence = float(mention.get("confidence", 0.0) or 0.0)

            resolved_entity_id, resolved_confidence = await self._resolve_entity_id(
                mention=mention,
                entity_type=entity_type,
                mention_text=mention_text,
                mention_confidence=mention_confidence,
                event=event,
            )

            await self._entity_catalog.record_mention(
                mention_text=mention_text,
                normalized_surface=normalized_surface,
                entity_type=entity_type,
                evidence_event_ids=[event.event_id],
                evidence_text=evidence_text,
                resolved_entity_id=resolved_entity_id,
                confidence=resolved_confidence,
            )
            resolved_mentions.append(
                {
                    "mention_text": mention_text,
                    "normalized_surface": normalized_surface,
                    "entity_type": entity_type,
                    "resolved_entity_id": resolved_entity_id,
                    "confidence": resolved_confidence,
                }
            )
        return resolved_mentions

    async def _resolve_entity_id(
        self,
        *,
        mention: dict[str, Any],
        entity_type: Optional[str],
        mention_text: str,
        mention_confidence: float,
        event: MemoryEvent,
    ) -> tuple[Optional[str], Optional[float]]:
        if self._entity_catalog is None:
            return (None, None)

        alias_resolution = await self._entity_catalog.resolve_alias(
            mention_text,
            entity_type=entity_type,
        )
        if alias_resolution.get("decision") == "match":
            return (str(alias_resolution["entity_id"]), float(alias_resolution["matched_confidence"]))

        if self._llm_service is not None and entity_type:
            candidate_entities = await self._entity_catalog.list_entities_by_type(entity_type=entity_type, limit=20)
            if candidate_entities:
                llm_resolution = await self._llm_service.resolve_entity(
                    mention={
                        "mention_text": mention_text,
                        "entity_type": entity_type,
                        "context_text": event.content,
                    },
                    candidate_entities=candidate_entities,
                )
                if llm_resolution.get("decision") == "match":
                    return (
                        str(llm_resolution["matched_entity_id"]),
                        float(llm_resolution.get("confidence", mention_confidence)),
                    )

        canonical_name = self._non_empty_text(mention.get("canonical_name_hint")) or mention_text
        if not entity_type or mention_confidence < 0.9:
            return (None, mention_confidence if mention_confidence > 0.0 else None)

        entity_id = self._build_canonical_entity_id(entity_type=entity_type, canonical_name=canonical_name)
        await self._entity_catalog.upsert_entity(
            entity_id=entity_id,
            canonical_name=canonical_name,
            entity_type=entity_type,
        )
        await self._entity_catalog.add_alias(
            entity_id=entity_id,
            alias_text=mention_text,
            confidence=min(max(mention_confidence, 0.9), 0.99),
        )
        for alias in mention.get("alias_signals", []):
            alias_text = self._non_empty_text(alias)
            if not alias_text:
                continue
            await self._entity_catalog.add_alias(
                entity_id=entity_id,
                alias_text=alias_text,
                confidence=min(max(mention_confidence, 0.85), 0.95),
            )
        return (entity_id, mention_confidence)

    def _build_graph_candidates(
        self,
        event: MemoryEvent,
        resolved_mentions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        subject_id = self._resolve_self_entity_id(event)
        if subject_id is None:
            return []

        text = event.content.casefold()
        predicate: Optional[str] = None
        if any(marker in text for marker in _NEGATIVE_PREFERENCE_MARKERS):
            predicate = "DISLIKES"
        elif any(marker in text for marker in _POSITIVE_PREFERENCE_MARKERS):
            predicate = "LIKES"
        if predicate is None:
            return []

        for mention in resolved_mentions:
            entity_type = self._normalize_entity_type(mention.get("entity_type"))
            if entity_type not in _GRAPH_ELIGIBLE_ENTITY_TYPES:
                continue
            object_id = mention.get("resolved_entity_id") or self._build_concept_node(
                entity_type=entity_type,
                normalized_surface=str(mention.get("normalized_surface") or mention.get("mention_text") or ""),
            )
            if not object_id:
                continue
            return [
                {
                    "subject_id": subject_id,
                    "subject_type": "user",
                    "predicate": predicate,
                    "object_id": object_id,
                    "object_type": entity_type,
                    "evidence_event_ids": [event.event_id],
                    "confidence": 0.78 if mention.get("resolved_entity_id") else 0.66,
                    "observed_at": event.timestamp,
                    "source_type": event.source,
                    "extraction_method": "pipeline_preference_rule",
                }
            ]
        return []

    def _build_focal_entities(
        self,
        event: MemoryEvent,
        resolved_mentions: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        focal_entities: list[dict[str, str]] = []
        self_entity_id = self._resolve_self_entity_id(event)
        if self_entity_id:
            focal_entities.append({"entity_id": self_entity_id, "entity_type": "user"})
        seen = {item["entity_id"] for item in focal_entities}
        for mention in resolved_mentions:
            entity_id = mention.get("resolved_entity_id")
            entity_type = self._normalize_entity_type(mention.get("entity_type"))
            if not entity_id or not entity_type or entity_id in seen:
                continue
            focal_entities.append({"entity_id": str(entity_id), "entity_type": entity_type})
            seen.add(str(entity_id))
        return focal_entities

    def _prepare_unified_graph_candidates(
        self,
        *,
        event: MemoryEvent,
        profile: ExtractionProfile,
        policy: Any,
        resolved_mentions: list[dict[str, Any]],
        resolved_context_refs: list[dict[str, Any]],
        raw_candidates: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], int]:
        if not policy.allow_graph_write or not profile.allow_graph or policy.graph_scope != "full":
            return [], 0

        prepared: list[dict[str, Any]] = []
        rejected_count = 0
        for raw_candidate in raw_candidates:
            if not isinstance(raw_candidate, dict):
                rejected_count += 1
                continue
            object_type = self._normalize_entity_type(raw_candidate.get("object_type"))
            predicate = self._normalize_predicate(raw_candidate.get("predicate"))
            if object_type not in profile.allowed_entity_types:
                rejected_count += 1
                continue
            if predicate not in profile.allowed_predicates:
                rejected_count += 1
                continue
            is_valid, _ = validate_graph_candidate(
                {
                    "predicate": predicate,
                    "object_type": object_type,
                }
            )
            if not is_valid:
                rejected_count += 1
                continue

            subject_id = self._resolve_subject_id(event=event, raw_candidate=raw_candidate)
            if not subject_id:
                rejected_count += 1
                continue
            object_id = self._resolve_graph_object_id(
                raw_object_ref=raw_candidate.get("object_ref"),
                object_type=object_type,
                resolved_mentions=resolved_mentions,
                resolved_context_refs=resolved_context_refs,
            )
            if not object_id:
                rejected_count += 1
                continue
            prepared.append(
                {
                    "subject_id": subject_id,
                    "subject_type": str(raw_candidate.get("subject_type", "user")).strip() or "user",
                    "predicate": predicate,
                    "object_id": object_id,
                    "object_type": object_type,
                    "evidence_event_ids": [event.event_id],
                    "confidence": float(raw_candidate.get("confidence", 0.0) or 0.0),
                    "observed_at": event.timestamp,
                    "source_type": event.source,
                    "extraction_method": "llm_unified_extraction",
                }
            )
        return prepared, rejected_count

    def _prepare_unified_assertion_candidates(
        self,
        *,
        event: MemoryEvent,
        profile: ExtractionProfile,
        policy: Any,
        graph_candidates: list[dict[str, Any]],
        resolved_context_refs: list[dict[str, Any]],
        raw_candidates: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], int]:
        if not policy.allow_assertion_write or not profile.allow_assertion:
            return [], 0

        scoped_assertions = self._apply_assertion_scope(
            raw_candidates=raw_candidates,
            assertion_scope=policy.assertion_scope,
        )
        prepared: list[dict[str, Any]] = []
        rejected_count = max(0, len(raw_candidates) - len(scoped_assertions))
        duplicate_check_candidates = [
            {
                "predicate": candidate["predicate"],
                "object_ref": candidate["object_id"],
            }
            for candidate in graph_candidates
        ]
        for raw_candidate in scoped_assertions:
            if not isinstance(raw_candidate, dict):
                rejected_count += 1
                continue
            if str(raw_candidate.get("trait_family", "")).strip().lower() not in profile.allowed_assertion_families:
                rejected_count += 1
                continue
            is_valid, _ = validate_assertion_candidate(raw_candidate)
            if not is_valid:
                rejected_count += 1
                continue
            if is_leaf_fact_duplicate(duplicate_check_candidates, raw_candidate):
                rejected_count += 1
                continue
            prepared.append(self._normalize_assertion_candidate(event, raw_candidate, resolved_context_refs))
        return prepared, rejected_count

    def _resolve_subject_id(self, *, event: MemoryEvent, raw_candidate: dict[str, Any]) -> str | None:
        subject_ref = self._non_empty_text(raw_candidate.get("subject_ref"))
        if subject_ref:
            if subject_ref.startswith("user:"):
                return self._resolve_self_entity_id(event) or subject_ref
            return subject_ref
        return self._resolve_self_entity_id(event)

    def _resolve_graph_object_id(
        self,
        *,
        raw_object_ref: Any,
        object_type: str,
        resolved_mentions: list[dict[str, Any]],
        resolved_context_refs: list[dict[str, Any]],
    ) -> str | None:
        object_ref = self._non_empty_text(raw_object_ref)
        if not object_ref:
            return None
        if ":" in object_ref:
            return object_ref
        object_ref_casefold = object_ref.casefold()
        for context_ref in resolved_context_refs:
            surface = self._non_empty_text(context_ref.get("surface"))
            resolved_ref = self._non_empty_text(context_ref.get("resolved_ref"))
            if surface and resolved_ref and surface.casefold() == object_ref_casefold:
                return resolved_ref
        for mention in resolved_mentions:
            surfaces = {
                str(mention.get("mention_text", "")).strip().casefold(),
                str(mention.get("normalized_surface", "")).strip().casefold(),
            }
            resolved_entity_id = self._non_empty_text(mention.get("resolved_entity_id"))
            if object_ref_casefold in surfaces and resolved_entity_id:
                return resolved_entity_id
        return self._build_concept_node(entity_type=object_type, normalized_surface=object_ref)

    def _normalize_assertion_candidate(
        self,
        event: MemoryEvent,
        candidate: dict[str, Any],
        resolved_context_refs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        trait_value = candidate.get("trait_value")
        if isinstance(trait_value, (dict, list)):
            trait_value = json.dumps(trait_value, ensure_ascii=False, sort_keys=True)
        elif trait_value is None:
            trait_value = ""
        self_entity_id = self._resolve_self_entity_id(event)
        entity_ref = self._non_empty_text(candidate.get("entity_ref"))
        if entity_ref and entity_ref.startswith("user:") and self_entity_id:
            entity_ref = self_entity_id
        target_entity_id, target_entity_type, context_ref_id = self._resolve_assertion_target(
            candidate=candidate,
            resolved_context_refs=resolved_context_refs,
        )
        temporal_scope, decay_policy, expires_at = self._derive_assertion_decay(
            event=event,
            candidate=candidate,
            target_entity_id=target_entity_id,
        )
        return {
            "entity_id": entity_ref or self_entity_id or "",
            "entity_type": str(candidate.get("entity_type", "user")),
            "trait_family": str(candidate.get("trait_family", "")).strip().lower(),
            "trait_name": str(candidate.get("trait_name", "")).strip(),
            "trait_value": str(trait_value),
            "confidence_score": float(candidate.get("confidence", 0.0) or 0.0),
            "evidence_events": [str(item) for item in candidate.get("supporting_event_ids", [event.event_id])],
            "volatility_index": float(candidate.get("volatility_index", 0.5) or 0.5),
            "source_domain": event.memory_domain.label,
            "inference_depth": str(candidate.get("inference_depth", event.tom_depth.label)),
            "validation_state": str(candidate.get("validation_state", "tentative")),
            "first_inferred_at": event.timestamp,
            "last_validated_at": event.timestamp,
            "target_entity_id": target_entity_id or "",
            "target_entity_type": target_entity_type or "",
            "target_scope": "entity_bound" if target_entity_id else "global",
            "temporal_scope": temporal_scope,
            "decay_policy": decay_policy,
            "decay_anchor_at": event.timestamp,
            "context_ref_id": context_ref_id or "",
            "expires_at": expires_at,
        }

    async def _collect_context_bundle(self, event: MemoryEvent, *, context_texts: list[str]) -> ContextBundle:
        recent_entities: list[dict[str, Any]] = []
        if self._entity_catalog is not None:
            recent_entities = await self._entity_catalog.list_mentions(limit=20)
        return collect_context_bundle(
            event=event,
            recent_messages=[{"text": text} for text in context_texts if text],
            recent_entities=recent_entities,
            live_context_entities=self._parse_live_context_entities(event),
            source_event_ids=self._load_source_event_ids(event),
        )

    def _merge_resolved_context_refs(
        self,
        *,
        direct_refs: list[Any],
        llm_refs: list[dict[str, Any]],
        context_bundle: ContextBundle,
    ) -> list[dict[str, Any]]:
        allowed_refs = {
            item.context_id: item.kind
            for item in context_bundle.live_context_entities
            if item.expires_at is None or item.expires_at > time.time()
        }
        merged: dict[str, dict[str, Any]] = {}
        for ref in direct_refs:
            payload = ref.to_dict() if hasattr(ref, "to_dict") else dict(ref)
            merged[str(payload.get("surface", ""))] = payload
        for ref in llm_refs:
            if not isinstance(ref, dict):
                continue
            surface = self._non_empty_text(ref.get("surface"))
            if not surface:
                continue
            resolved_ref = self._non_empty_text(ref.get("resolved_ref"))
            reference_type = self._non_empty_text(ref.get("reference_type")) or "unresolved"
            if reference_type == "context_entity":
                if not resolved_ref or resolved_ref not in allowed_refs:
                    continue
            merged[surface] = dict(ref)
        return list(merged.values())

    def _resolve_assertion_target(
        self,
        *,
        candidate: dict[str, Any],
        resolved_context_refs: list[dict[str, Any]],
    ) -> tuple[str | None, str | None, str | None]:
        target_ref = self._non_empty_text(candidate.get("target_ref"))
        explicit_target_entity_id = self._non_empty_text(candidate.get("target_entity_id"))
        explicit_target_entity_type = self._normalize_entity_type(candidate.get("target_entity_type"))
        if explicit_target_entity_id:
            return explicit_target_entity_id, explicit_target_entity_type, explicit_target_entity_id
        if not target_ref:
            return None, None, None
        target_ref_casefold = target_ref.casefold()
        for context_ref in resolved_context_refs:
            surface = self._non_empty_text(context_ref.get("surface"))
            resolved_ref = self._non_empty_text(context_ref.get("resolved_ref"))
            if surface and resolved_ref and surface.casefold() == target_ref_casefold:
                kind = self._normalize_entity_type(context_ref.get("resolved_kind")) or self._normalize_entity_type(
                    resolved_ref.split(":", 1)[0]
                )
                return resolved_ref, kind, resolved_ref
        return None, None, None

    def _derive_assertion_decay(
        self,
        *,
        event: MemoryEvent,
        candidate: dict[str, Any],
        target_entity_id: str | None,
    ) -> tuple[str, str, float | None]:
        temporal_scope = self._non_empty_text(candidate.get("temporal_scope"))
        decay_policy = self._non_empty_text(candidate.get("decay_policy"))
        expires_at = candidate.get("expires_at")
        if temporal_scope and decay_policy:
            return temporal_scope, decay_policy, float(expires_at) if expires_at is not None else None

        trait_family = str(candidate.get("trait_family", "")).strip().lower()
        trait_name = str(candidate.get("trait_name", "")).strip().lower()
        if target_entity_id and trait_name in {"annoyance", "irritation", "frustration"}:
            return "momentary", "fast_decay", event.timestamp + 2 * 60 * 60
        if trait_family == "mood":
            return "session", "session_decay", event.timestamp + 12 * 60 * 60
        if trait_family == "stress":
            return "daily", "time_window", event.timestamp + 24 * 60 * 60
        if trait_family == "engagement":
            return "session", "session_decay", event.timestamp + 12 * 60 * 60
        if trait_family in {"group_atmosphere", "public_sentiment", "relationship_shift"}:
            return "session", "session_decay", event.timestamp + 6 * 60 * 60
        return "stable", "evidence_only", None

    def _parse_live_context_entities(self, event: MemoryEvent) -> list[ContextEntity]:
        raw_entities: list[dict[str, Any]] = []
        entities: list[ContextEntity] = []
        for item in raw_entities if isinstance(raw_entities, list) else []:
            if not isinstance(item, dict):
                continue
            context_id = self._non_empty_text(item.get("context_id"))
            kind = self._normalize_entity_type(item.get("kind"))
            summary = self._non_empty_text(item.get("summary"))
            if not context_id or not kind or not summary:
                continue
            entities.append(
                ContextEntity(
                    context_id=context_id,
                    kind=kind,
                    summary=summary,
                    payload=item.get("payload", {}) if isinstance(item.get("payload"), dict) else {},
                    source_event_ids=[str(value) for value in item.get("source_event_ids", []) if str(value).strip()],
                    created_at=float(item.get("created_at", event.timestamp) or event.timestamp),
                    expires_at=float(item["expires_at"]) if item.get("expires_at") is not None else None,
                )
            )
        return entities

    def _load_source_event_ids(self, event: MemoryEvent) -> list[str]:
        return []

    def _parse_json_object(self, raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        if not raw:
            return {}
        try:
            parsed = json.loads(str(raw))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _collect_touched_entities(
        self,
        graph_candidates: list[dict[str, Any]],
        assertion_candidates: list[dict[str, Any]],
    ) -> list[str]:
        touched: set[str] = set()
        for candidate in graph_candidates:
            subject_id = candidate.get("subject_id")
            object_id = candidate.get("object_id")
            if subject_id:
                touched.add(str(subject_id))
            if object_id:
                touched.add(str(object_id))
        for candidate in assertion_candidates:
            entity_id = candidate.get("entity_id")
            if entity_id:
                touched.add(str(entity_id))
        return sorted(touched)

    def _resolve_self_entity_id(self, event: MemoryEvent) -> str | None:
        if event.user_id:
            return f"user:{event.user_id}"
        return None

    def _apply_assertion_scope(
        self,
        *,
        raw_candidates: list[dict[str, Any]],
        assertion_scope: str,
    ) -> list[dict[str, Any]]:
        if assertion_scope == "none":
            return []
        if assertion_scope == "full":
            return [candidate for candidate in raw_candidates if isinstance(candidate, dict)]
        if assertion_scope == "topology_only":
            return [
                candidate
                for candidate in raw_candidates
                if isinstance(candidate, dict)
                and str(candidate.get("trait_family", "")).strip().casefold() in _TOPOLOGY_ONLY_TRAIT_FAMILIES
            ]
        return []

    def _increment_bucket(self, bucket: dict[str, int], key: str | None) -> None:
        if not key:
            return
        bucket[key] = int(bucket.get(key, 0)) + 1

    def _normalize_entity_type(self, raw_value: Any) -> Optional[str]:
        text = self._non_empty_text(raw_value)
        if text is None:
            return None
        return coerce_unknown_entity_type(text)

    def _normalize_predicate(self, raw_value: Any) -> Optional[str]:
        text = self._non_empty_text(raw_value)
        return text.upper() if text else None

    def _build_concept_node(self, *, entity_type: str, normalized_surface: str) -> Optional[str]:
        surface = self._non_empty_text(normalized_surface)
        if not surface:
            return None
        slug = self._slugify(surface)
        return f"{entity_type}:{slug}"

    def _build_canonical_entity_id(self, *, entity_type: str, canonical_name: str) -> str:
        slug = self._slugify(canonical_name)
        return f"{entity_type}:{slug}"

    def _slugify(self, value: str) -> str:
        normalized = value.strip().casefold()
        slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
        if slug:
            return slug
        return uuid.uuid5(uuid.NAMESPACE_URL, normalized).hex[:12]

    def _non_empty_text(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    async def _detect_contradiction_hints(
        self,
        *,
        event: MemoryEvent,
        focal_entities: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        if self._cognition_store is None or self._llm_service is None:
            return []

        existing_records = await self._load_existing_records(focal_entities)
        if not existing_records:
            return []

        return await self._llm_service.detect_contradiction_hints(
            new_event={
                "event_id": event.event_id,
                "event_type": event.event_type,
                "content": event.content,
                "source": event.source,
                "timestamp": event.timestamp,
            },
            existing_records=existing_records,
        )

    async def _load_existing_records(self, focal_entities: list[dict[str, str]]) -> list[dict[str, Any]]:
        if self._cognition_store is None:
            return []

        records: list[dict[str, Any]] = []
        seen_record_ids: set[str] = set()
        for entity in focal_entities:
            entity_id = entity["entity_id"]
            entity_type = entity["entity_type"]
            assertions = await self._cognition_store.list_tom_assertions(
                entity_id=entity_id,
                entity_type=entity_type,
                limit=50,
            )
            for assertion in assertions:
                record_id = str(assertion["assertion_id"])
                if record_id in seen_record_ids:
                    continue
                seen_record_ids.add(record_id)
                records.append(
                    {
                        "record_id": record_id,
                        "record_type": "tom_trait_assertion",
                        "entity_id": assertion["entity_id"],
                        "entity_type": assertion["entity_type"],
                        "trait_name": assertion["trait_name"],
                        "trait_value": assertion["trait_value"],
                        "validation_state": assertion["validation_state"],
                        "confidence": assertion["confidence_score"],
                    }
                )

            relations = await self._cognition_store.get_relationships(subject_id=entity_id, limit=50)
            relations.extend(await self._cognition_store.get_relationships(object_id=entity_id, limit=50))
            for relation in relations:
                record_id = str(relation["triple_id"])
                if record_id in seen_record_ids:
                    continue
                seen_record_ids.add(record_id)
                records.append(
                    {
                        "record_id": record_id,
                        "record_type": "knowledge_graph",
                        "subject_id": relation["subject_id"],
                        "predicate": relation["predicate"],
                        "object_id": relation["object_id"],
                        "status": relation["status"],
                        "confidence": relation["confidence"],
                    }
                )
        return records

    async def _load_evidence_timestamps(self, entity_id: str) -> dict[str, float]:
        if self._l1_store is None or self._cognition_store is None:
            return {}
        entity_type = self._entity_type_from_id(entity_id)
        assertions = await self._cognition_store.list_tom_assertions(entity_id=entity_id, entity_type=entity_type, limit=500)
        event_ids = sorted({event_id for item in assertions for event_id in item.get("evidence_events", [])})
        timestamps: dict[str, float] = {}
        for event_id in event_ids:
            event = await self._l1_store.get_event(event_id)
            if event is None:
                continue
            timestamps[event_id] = float(event["timestamp"])
        return timestamps

    def _entity_type_from_id(self, entity_id: str) -> str:
        prefix, _, _ = entity_id.partition(":")
        return prefix or "entity"


__all__ = ["L2Pipeline", "L2PipelineStats"]
