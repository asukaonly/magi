"""Asynchronous queue workers for L2 cognition processing."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Optional

from .event_contracts import IngestTarget, MemoryDomain, MemoryEvent, RetentionClass, TomDepth
from .l1_event_store import L1EventStore
from .l2_cognition_store import L2CognitionStore
from .l2_entity_catalog import L2EntityCatalog
from .l2_llm_service import L2LLMService

_POSITIVE_PREFERENCE_MARKERS = (" like ", " likes ", "喜欢", "love ", "loves ")
_NEGATIVE_PREFERENCE_MARKERS = (" dislike ", " dislikes ", "不喜欢", "do not like", "don't like")
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
                result = await self._extract_and_persist(event)
                self._stats.extract_completed += 1
                self._stats.relations_written += int(result["relation_count"])
                self._stats.assertions_written += int(result["assertion_count"])
                touched_entity_ids = result.get("touched_entity_ids", [])
                if isinstance(touched_entity_ids, list) and touched_entity_ids:
                    await self.enqueue_entities(touched_entity_ids)
            except Exception:
                self._stats.extract_failed += 1
            finally:
                self._extract_queue.task_done()

    async def _run_reconcile_worker(self) -> None:
        while True:
            entity_ids = await self._reconcile_queue.get()
            try:
                if entity_ids is None:
                    break
                self._stats.reconcile_completed += 1
            except Exception:
                self._stats.reconcile_failed += 1
            finally:
                self._reconcile_queue.task_done()

    async def _run_snapshot_worker(self) -> None:
        while True:
            entity_ids = await self._snapshot_queue.get()
            try:
                if entity_ids is None:
                    break
                self._stats.snapshot_completed += 1
            except Exception:
                self._stats.snapshot_failed += 1
            finally:
                self._snapshot_queue.task_done()

    async def _extract_and_persist(self, event: MemoryEvent) -> dict[str, Any]:
        if self._cognition_store is None:
            return {"relation_count": 0, "assertion_count": 0, "touched_entity_ids": []}

        stored_event = await self._load_stored_event(event)
        if self._entity_catalog is None or self._llm_service is None:
            legacy_result = await self._cognition_store.apply_memory_event(stored_event)
            return {
                **legacy_result,
                "touched_entity_ids": self._collect_touched_entities(stored_event, [], []),
            }

        context_texts = await self._load_context_texts(stored_event)
        mentions = await self._llm_service.extract_entity_mentions(
            event_text=stored_event.raw_content,
            context_texts=context_texts,
        )
        resolved_mentions = await self._resolve_mentions(stored_event, mentions)

        graph_candidates = self._build_graph_candidates(stored_event, resolved_mentions)
        if not graph_candidates:
            graph_candidates = self._cognition_store.extract_graph_candidates(stored_event)

        focal_entities = self._build_focal_entities(stored_event, resolved_mentions)
        llm_assertions = await self._llm_service.extract_tom_assertions(
            event_window={
                "event_ids": [stored_event.event_id],
                "texts": [stored_event.raw_content],
                "context_texts": context_texts,
            },
            focal_entities=focal_entities,
        )
        assertion_candidates = (
            [self._normalize_assertion_candidate(stored_event, candidate) for candidate in llm_assertions]
            if llm_assertions
            else self._cognition_store.extract_assertion_candidates(stored_event)
        )

        relation_count = 0
        assertion_count = 0
        for candidate in graph_candidates:
            await self._cognition_store.upsert_knowledge_edge(**candidate)
            relation_count += 1

        for candidate in assertion_candidates:
            await self._cognition_store.upsert_assertion_candidate(candidate)
            assertion_count += 1

        return {
            "relation_count": relation_count,
            "assertion_count": assertion_count,
            "touched_entity_ids": self._collect_touched_entities(stored_event, resolved_mentions, assertion_candidates),
        }

    async def _load_stored_event(self, event: MemoryEvent) -> MemoryEvent:
        if self._l1_store is None:
            return event
        row = await self._l1_store.get_event(event.event_id)
        if row is None:
            return event
        return MemoryEvent(
            event_id=str(row["event_id"]),
            correlation_id=str(row["correlation_id"]),
            parent_event_id=row["parent_event_id"],
            timestamp=float(row["timestamp"]),
            created_at=float(row["created_at"]),
            event_type=str(row["event_type"]),
            source=str(row["source"]),
            source_item_id=row["source_item_id"],
            memory_domain=MemoryDomain.from_value(row["memory_domain"]),
            ingest_target=IngestTarget.from_value(row["ingest_target"]),
            cognition_eligible=bool(row["cognition_eligible"]),
            tom_depth=TomDepth.from_value(row["tom_depth"]),
            retention_class=RetentionClass.from_value(row["retention_class"]),
            session_id=row["session_id"],
            user_id=row["user_id"],
            task_id=row["task_id"],
            goal_id=row["goal_id"],
            raw_content=str(row["raw_content"]),
            structured_payload=json.dumps(row.get("structured_payload", {}), ensure_ascii=False),
            metadata=json.dumps(row.get("metadata", {}), ensure_ascii=False),
            importance_score=float(row["importance_score"]),
            importance_t0_base=float(row["importance_t0_base"] or 0.0),
            importance_t1_score=float(row["importance_t1_score"]) if row["importance_t1_score"] is not None else None,
            importance_version=int(row["importance_version"]),
            level=int(row["level"]),
            media_path=row["media_path"],
            entity_focus_hint=self._extract_entity_focus_hint(row),
        )

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
        event: MemoryEvent,
        resolved_mentions: list[dict[str, Any]],
        assertion_candidates: list[dict[str, Any]],
    ) -> list[str]:
        touched: set[str] = set()
        if event.user_id:
            touched.add(f"user:{event.user_id}")
        for mention in resolved_mentions:
            entity_id = mention.get("resolved_entity_id")
            if entity_id:
                touched.add(str(entity_id))
        for candidate in assertion_candidates:
            entity_id = candidate.get("entity_id")
            if entity_id:
                touched.add(str(entity_id))
        return sorted(touched)

    def _extract_entity_focus_hint(self, row: dict[str, Any]) -> Optional[str]:
        structured_payload = row.get("structured_payload")
        metadata = row.get("metadata")
        if isinstance(structured_payload, dict):
            payload_hint = self._non_empty_text(structured_payload.get("entity_focus_hint"))
            if payload_hint:
                return payload_hint
        if isinstance(metadata, dict):
            metadata_hint = self._non_empty_text(metadata.get("entity_focus_hint"))
            if metadata_hint:
                return metadata_hint
        return None

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


__all__ = ["L2Pipeline", "L2PipelineStats"]
