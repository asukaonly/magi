"""Asynchronous queue workers for L2 cognition processing."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from ..core.logger import get_logger
from .event_contracts import MemoryEvent
from .l1_event_store import L1EventStore
from .l2_cognition_store import L2CognitionStore
from .l2_evidence_classifier import classify_event_evidence
from .l2_evidence_policy import resolve_l2_policy
from .l2_entity_catalog import L2EntityCatalog
from .l2_llm_service import L2LLMService

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
    ) -> None:
        self._cognition_store = cognition_store
        self._l1_store = l1_store
        self._entity_catalog = entity_catalog
        self._llm_service = llm_service
        self._extract_queue: asyncio.Queue[MemoryEvent | None] = asyncio.Queue()
        self._reconcile_queue: asyncio.Queue[list[str] | None] = asyncio.Queue()
        self._snapshot_queue: asyncio.Queue[list[str] | None] = asyncio.Queue()
        self._extract_worker: asyncio.Task[None] | None = None
        self._reconcile_worker: asyncio.Task[None] | None = None
        self._snapshot_worker: asyncio.Task[None] | None = None
        self._stats = L2PipelineStats()

    async def start(self) -> None:
        if self._stats.is_running or self._cognition_store is None:
            return

        self._stats.is_running = True
        self._extract_worker = asyncio.create_task(self._run_extract_worker())
        self._reconcile_worker = asyncio.create_task(self._run_reconcile_worker())
        self._snapshot_worker = asyncio.create_task(self._run_snapshot_worker())

    async def shutdown(self) -> None:
        if not self._stats.is_running:
            return

        self._stats.is_running = False
        await self._extract_queue.put(None)
        await self._reconcile_queue.put(None)
        await self._snapshot_queue.put(None)

        for worker in (self._extract_worker, self._reconcile_worker, self._snapshot_worker):
            if worker is None:
                continue
            try:
                await worker
            except asyncio.CancelledError:
                pass

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
            if policy.allow_entity_extraction or policy.allow_assertion_write
            else []
        )
        resolved_mentions: list[dict[str, Any]] = []
        if policy.allow_entity_extraction:
            mentions = await self._llm_service.extract_entity_mentions(
                event_text=stored_event.raw_content,
                context_texts=context_texts,
            )
            resolved_mentions = await self._resolve_mentions(stored_event, mentions)
            logger.debug(
                "L2 mentions resolved",
                event_id=stored_event.event_id,
                mention_count=len(mentions),
                resolved_mention_count=len(resolved_mentions),
            )

        graph_candidates: list[dict[str, Any]] = []
        if policy.allow_graph_write and policy.graph_scope == "full":
            graph_candidates = self._build_graph_candidates(stored_event, resolved_mentions)
            if not graph_candidates:
                graph_candidates = self._cognition_store.extract_graph_candidates(stored_event)

        focal_entities = self._build_focal_entities(stored_event, resolved_mentions)
        assertion_candidates: list[dict[str, Any]] = []
        if policy.allow_assertion_write:
            llm_assertions = await self._llm_service.extract_tom_assertions(
                event_window={
                    "event_ids": [stored_event.event_id],
                    "texts": [stored_event.raw_content],
                    "context_texts": context_texts,
                },
                focal_entities=focal_entities,
            )
            scoped_assertions = self._apply_assertion_scope(
                raw_candidates=llm_assertions,
                assertion_scope=policy.assertion_scope,
            )
            if scoped_assertions:
                assertion_candidates = [
                    self._normalize_assertion_candidate(stored_event, candidate) for candidate in scoped_assertions
                ]
            elif policy.assertion_scope == "full":
                assertion_candidates = self._cognition_store.extract_assertion_candidates(stored_event)
        logger.debug(
            "L2 candidates built",
            event_id=stored_event.event_id,
            graph_candidate_count=len(graph_candidates),
            assertion_candidate_count=len(assertion_candidates),
            focal_entity_count=len(focal_entities),
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

        return {
            "relation_count": relation_count,
            "assertion_count": assertion_count,
            "touched_entity_ids": self._collect_touched_entities(graph_candidates, assertion_candidates),
            "skipped": False,
            "evidence_class": classification.evidence_class,
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
        context_texts = [str(row["raw_content"]) for row in reversed(context_rows) if str(row["raw_content"]).strip()]
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
            evidence_text = self._non_empty_text(mention.get("evidence_text")) or event.raw_content
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
                        "context_text": event.raw_content,
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
        subject_id = f"user:{event.user_id}" if event.user_id else None
        if subject_id is None:
            return []

        text = event.raw_content.casefold()
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
        if event.user_id:
            focal_entities.append({"entity_id": f"user:{event.user_id}", "entity_type": "user"})
        seen = {item["entity_id"] for item in focal_entities}
        for mention in resolved_mentions:
            entity_id = mention.get("resolved_entity_id")
            entity_type = self._normalize_entity_type(mention.get("entity_type"))
            if not entity_id or not entity_type or entity_id in seen:
                continue
            focal_entities.append({"entity_id": str(entity_id), "entity_type": entity_type})
            seen.add(str(entity_id))
        return focal_entities

    def _normalize_assertion_candidate(
        self,
        event: MemoryEvent,
        candidate: dict[str, Any],
    ) -> dict[str, Any]:
        trait_value = candidate.get("trait_value")
        if isinstance(trait_value, (dict, list)):
            trait_value = json.dumps(trait_value, ensure_ascii=False, sort_keys=True)
        elif trait_value is None:
            trait_value = ""
        return {
            "entity_id": str(candidate.get("entity_ref", f"user:{event.user_id}" if event.user_id else "")),
            "entity_type": str(candidate.get("entity_type", "user")),
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
        }

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
        return text.casefold() if text else None

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
                "raw_content": event.raw_content,
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
