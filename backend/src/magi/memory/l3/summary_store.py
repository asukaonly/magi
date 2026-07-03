"""L3 reflection memory store."""

from __future__ import annotations

import logging
import asyncio
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from ...config.models import EmbeddingBackend
from ...llm import ScenarioLLMPool
from ..embedding.embedding_service import MemoryEmbeddingService
from ..l1.event_store import L1EventStore
from ..embedding.sqlite_vec_index import SqliteVecIndex
from .episode_backwrite import backwrite_episode_summary, episode_needs_summary_backfill
from .evidence_selector import TemporalEvidenceSelection, select_temporal_evidence
from .episodic_service import EpisodicSummaryLLMService
from .topic_llm_service import TopicSummaryLLMService
from .temporal_llm_service import TemporalSummaryLLMService
from .validator import validate_candidate
from .models import (
    L3Candidate,
    TemporalEvidencePack,
    TemporalGenerationResult,
    ThematicEvidencePack,
    ThematicGenerationResult,
)
from .embeddings.operations import L3SummaryEmbeddingMixin
from .retrieval.operations import L3SummarySearchMixin
from .storage.schema import ensure_l3_summary_schema
from .storage.operations import L3SummaryPersistenceMixin
from .storage.review_operations import L3ReviewOperationsMixin

logger = logging.getLogger(__name__)

_PREVIOUS_PERIOD_CONTEXT_LIMITS = {
    "hour": 1,
    "day": 1,
    "week": 3,
    "month": 3,
    "quarter": 2,
    "year": 2,
}
_CHILD_PERIOD_CONTEXT_CATEGORIES = {
    "day": ["hour"],
    "week": ["day"],
    "month": ["week"],
    "quarter": ["month"],
    "year": ["quarter"],
}
_CHILD_PERIOD_CONTEXT_LIMIT_BY_PARENT = {
    "day": 24,
    "week": 8,
    "month": 6,
    "quarter": 4,
    "year": 5,
}
_CHILD_PERIOD_CONTEXT_LIMIT_DEFAULT = 6
_EXPERIENCE_PLACEHOLDER_TEXTS = {
    "untitled",
    "untitled episode",
    "untitled experience",
    "experience",
}
_EXPERIENCE_GENERIC_TEXTS = {
    "magi grouped related episode evidence into a narratable memory.",
}
_EXPERIENCE_MACHINE_ID_PATTERN = re.compile(
    r"^(?:[0-9a-f]{10,}|[0-9A-HJKMNP-TV-Z]{12,})$",
    re.IGNORECASE,
)
_EXPERIENCE_LOW_VALUE_LABELS = {
    "local_user",
    "local user",
    "self",
    "user",
    "user self",
}


def _is_placeholder_experience_text(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    lowered = text.lower()
    if lowered in _EXPERIENCE_PLACEHOLDER_TEXTS or lowered.startswith("untitled exper"):
        return True
    parts = [part.strip() for part in lowered.replace("|", "/").split("/") if part.strip()]
    return bool(parts) and all(
        part in _EXPERIENCE_PLACEHOLDER_TEXTS or part.startswith("untitled exper") for part in parts
    )


def _is_generic_experience_text(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text in _EXPERIENCE_GENERIC_TEXTS


def _experience_text_is_usable(value: Any) -> bool:
    return not _is_placeholder_experience_text(value) and not _is_generic_experience_text(value)


def _format_experience_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if ":" in text:
        _, _, text = text.partition(":")
    raw_text = text.strip()
    text = raw_text.replace("_", " ").replace("-", " ")
    if (
        not _experience_text_is_usable(text)
        or raw_text.isdigit()
        or _EXPERIENCE_MACHINE_ID_PATTERN.fullmatch(raw_text)
        or text.casefold() in _EXPERIENCE_LOW_VALUE_LABELS
    ):
        return ""
    return text


def _ordered_experience_labels(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        label = _format_experience_label(value)
        key = label.casefold()
        if label and key not in seen:
            seen.add(key)
            result.append(label)
    return result


def _experience_theme_labels(experience: dict[str, Any]) -> list[str]:
    return _ordered_experience_labels(
        [
            value
            for key in ("primary_entity_ids", "primary_place_ids", "primary_topic_keys")
            for value in (experience.get(key) or [])
        ]
    )


def _experience_fallback_label(
    experience: dict[str, Any],
    events: list[dict[str, Any]],
) -> str:
    for key in ("user_label", "title", "intent"):
        value = str(experience.get(key) or "").strip()
        if _experience_text_is_usable(value):
            return value[:36]

    labels = _experience_theme_labels(experience)
    if labels:
        return " / ".join(labels[:3])[:36]

    for event in events:
        content = str(event.get("content") or "").strip()
        if content:
            return content[:36]
    return "Experience"


def _experience_fallback_content(
    experience: dict[str, Any],
    events: list[dict[str, Any]],
    event_count: int,
) -> str:
    user_note = str(experience.get("user_note") or "").strip()
    if _experience_text_is_usable(user_note):
        return user_note[:240]

    for key in ("magi_interpretation", "outcome", "intent"):
        value = str(experience.get(key) or "").strip()
        if _experience_text_is_usable(value):
            return value[:240]

    snippets = [
        str(event.get("content") or "").strip()
        for event in events[:3]
        if str(event.get("content") or "").strip()
    ]
    if snippets:
        return "；".join(snippets)[:240]

    return f"包含 {event_count} 个事件的经历"


def _topic_fallback_summary(
    *,
    topic: str,
    source_event_count: int,
    topic_events: list[dict[str, Any]],
) -> str:
    snippets = [
        str(event.get("content") or "").strip()
        for event in topic_events[:4]
        if str(event.get("content") or "").strip()
    ]
    return (
        f"Topic '{topic}' recurred across {source_event_count} events. " + " ".join(snippets)
    ).strip()


def _event_timestamps(events: list[dict[str, Any]]) -> list[float]:
    return [float(event["timestamp"]) for event in events if event.get("timestamp") is not None]


def _summary_period_start(period_start: float | None, timestamps: list[float]) -> float:
    if period_start is not None:
        return float(period_start)
    return min(timestamps) if timestamps else time.time()


def _summary_period_end(period_end: float | None, timestamps: list[float]) -> float:
    if period_end is not None:
        return float(period_end)
    return max(timestamps) if timestamps else time.time()


def _temporal_fallback_summary(events: list[dict[str, Any]]) -> str:
    return " ".join(str(event.get("content") or "") for event in events[:6]).strip()


@dataclass(slots=True)
class _ExperienceSummaryContext:
    experience_id: str
    episode_ids: list[str]
    event_ids: list[str]
    events: list[dict[str, Any]]
    fallback_label: str
    fallback_content: str
    period_start: float
    period_end: float


@dataclass(slots=True)
class _ExperienceSummaryDraft:
    content: str
    source_event_ids: list[str]
    metadata: dict[str, Any]
    used_fallback: bool


class L3SummaryStore(
    L3SummaryEmbeddingMixin,
    L3SummarySearchMixin,
    L3SummaryPersistenceMixin,
    L3ReviewOperationsMixin,
):
    """Stores reflection-oriented summaries that remain traceable to L1 evidence."""

    def __init__(
        self,
        *,
        db_path: str = "~/.magi/data/memory/memory.db",
        embedding_service: MemoryEmbeddingService | None = None,
        memory_config_getter: Callable[[], Any] | None = None,
        vector_enabled: bool = True,
        async_embeddings: bool = True,
        enable_temporal_llm_summary: bool = True,
        temporal_llm_timeout_seconds: float = 3.0,
        temporal_llm_min_event_count: int = 2,
        scenario_llm_pool: ScenarioLLMPool | None = None,
        temporal_summary_features_builder: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self.db_path = str(Path(db_path).expanduser())
        self._embedding_service = embedding_service
        self._memory_config_getter = memory_config_getter
        self._default_vector_enabled = bool(vector_enabled and embedding_service is not None)
        self._default_async_embeddings = bool(async_embeddings)
        self._temporal_llm_service = TemporalSummaryLLMService(
            enabled=enable_temporal_llm_summary,
            llm_timeout_seconds=temporal_llm_timeout_seconds,
            min_event_count_for_llm=temporal_llm_min_event_count,
            scenario_llm_pool=scenario_llm_pool,
        )
        self._topic_llm_service = TopicSummaryLLMService(
            enabled=enable_temporal_llm_summary,
            llm_timeout_seconds=temporal_llm_timeout_seconds,
            scenario_llm_pool=scenario_llm_pool,
        )
        self._episodic_llm_service = EpisodicSummaryLLMService(
            enabled=True,
            llm_timeout_seconds=30.0,
            scenario_llm_pool=scenario_llm_pool,
        )
        self._temporal_summary_features_builder = temporal_summary_features_builder
        self._vector_index = (
            SqliteVecIndex(
                db_path=self.db_path,
                registry_table="l3_summary_chunk_vectors",
                entity_column="chunk_id",
                vec_table_prefix="l3_summary_chunk_vec",
            )
            if embedding_service is not None or vector_enabled
            else None
        )
        self._embedding_queue: asyncio.Queue[Dict[str, Any] | None] | None = (
            asyncio.Queue() if embedding_service is not None else None
        )
        self._embedding_worker: asyncio.Task[None] | None = None
        self._embedding_active_count = 0
        self._embedding_batch_size = 5
        self._embedding_batch_wait_seconds = 1.0
        self._initialized = False

    async def initialize(self) -> None:
        """Create the summaries schema."""
        if self._initialized:
            return

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with sqlite_connection_async(self.db_path) as db:
            if self._vector_index is not None:
                await self._vector_index.initialize()
            await ensure_l3_summary_schema(db)
            await db.commit()
        if self._embedding_queue is not None and self._embedding_worker is None:
            self._embedding_worker = asyncio.create_task(self._run_embedding_worker())
        self._initialized = True

    async def shutdown(self) -> None:
        if self._embedding_queue is not None and self._embedding_worker is not None:
            await self._embedding_queue.put(None)
            await self._embedding_worker
            self._embedding_worker = None
        if self._vector_index is not None:
            await self._vector_index.close()

    def _current_memory_config(self) -> Any | None:
        if self._memory_config_getter is None:
            return None
        try:
            return self._memory_config_getter()
        except Exception as exc:
            logger.debug("Failed to resolve current memory config: %s", exc)
            return None

    def _vectors_enabled(self) -> bool:
        if self._embedding_service is None:
            return False
        config = self._current_memory_config()
        if config is None:
            return self._default_vector_enabled
        return bool(
            config.embedding.backend == EmbeddingBackend.SQLITE_VEC
            and config.l3.enabled
            and config.l3.vectors_enabled
        )

    def _async_embeddings_enabled(self) -> bool:
        config = self._current_memory_config()
        if config is None:
            return self._default_async_embeddings
        return bool(config.async_embeddings)

    async def generate_temporal_summary(
        self,
        *,
        l1_store: L1EventStore,
        summary_category: str,
        period_start: float,
        period_end: float,
        source_filter: Optional[List[str]] = None,
        min_events: int = 1,
    ) -> Optional[Dict[str, Any]]:
        """Build a temporal summary from eligible L1 events."""
        await self.initialize()
        selection = await self._select_temporal_summary_events(
            l1_store=l1_store,
            period_start=period_start,
            period_end=period_end,
            source_filter=source_filter,
        )
        events = list(selection.selected_events)
        if len(events) < max(1, int(min_events)):
            return None

        evidence_pack = self._build_temporal_summary_evidence_pack(
            selection=selection,
            events=events,
            summary_category=summary_category,
            period_start=period_start,
            period_end=period_end,
            source_filter=source_filter,
        )
        if not evidence_pack.source_event_ids:
            return None
        await self._attach_temporal_summary_context(evidence_pack)

        generation = await self._generate_accepted_temporal_candidate(
            evidence_pack=evidence_pack,
            events=events,
            fallback_summary=_temporal_fallback_summary(events),
        )
        if generation is None:
            return None
        summary = await self.upsert_candidate(
            candidate=generation.candidate,
            summary_overrides=self._temporal_summary_overrides(
                selection=selection,
                evidence_pack=evidence_pack,
                generation=generation,
                summary_category=summary_category,
                period_start=period_start,
                period_end=period_end,
            ),
        )
        return summary

    async def _select_temporal_summary_events(
        self,
        *,
        l1_store: L1EventStore,
        period_start: float,
        period_end: float,
        source_filter: Optional[List[str]],
    ) -> TemporalEvidenceSelection:
        return await select_temporal_evidence(
            l1_store=l1_store,
            period_start=period_start,
            period_end=period_end,
            source_filter=list(source_filter) if source_filter else None,
        )

    def _build_temporal_summary_evidence_pack(
        self,
        *,
        selection: TemporalEvidenceSelection,
        events: list[dict[str, Any]],
        summary_category: str,
        period_start: float,
        period_end: float,
        source_filter: Optional[List[str]],
    ) -> TemporalEvidencePack:
        evidence_pack = self._temporal_llm_service.build_evidence_pack(
            events=events,
            summary_category=summary_category,
            period_start=period_start,
            period_end=period_end,
        )
        evidence_pack.window_event_count = int(selection.source_event_total)
        evidence_pack.omitted_event_count = int(selection.omitted_event_count)
        evidence_pack.source_distribution = dict(selection.source_distribution)
        evidence_pack.selection_policy = dict(selection.selection_policy)
        evidence_pack.plugin_summary_features = self._temporal_plugin_summary_features(
            selection=selection,
            summary_category=summary_category,
            period_start=period_start,
            period_end=period_end,
            source_filter=source_filter,
        )
        return evidence_pack

    def _temporal_plugin_summary_features(
        self,
        *,
        selection: TemporalEvidenceSelection,
        summary_category: str,
        period_start: float,
        period_end: float,
        source_filter: Optional[List[str]],
    ) -> dict[str, Any]:
        if self._temporal_summary_features_builder is None:
            return {}
        try:
            return dict(
                self._temporal_summary_features_builder(
                    events=list(selection.feature_events),
                    summary_category=summary_category,
                    period_start=period_start,
                    period_end=period_end,
                    source_filter=list(source_filter) if source_filter else None,
                    feature_budgets=dict(selection.feature_budgets),
                )
                or {}
            )
        except Exception as exc:
            logger.warning("L3 temporal summary features builder failed: %s", exc)
            return {}

    async def _generate_accepted_temporal_candidate(
        self,
        *,
        evidence_pack: TemporalEvidencePack,
        events: list[dict[str, Any]],
        fallback_summary: str,
    ) -> TemporalGenerationResult | None:
        generation = await self._temporal_llm_service.generate_temporal_candidate(
            evidence_pack,
            fallback_summary=fallback_summary,
        )
        decision = validate_candidate(generation.candidate, evidence_events=events)
        if decision.action != "accept" and not generation.used_fallback:
            generation = self._temporal_llm_service._build_fallback_result(
                evidence_pack,
                fallback_summary,
            )
            decision = validate_candidate(generation.candidate, evidence_events=events)
        return generation if decision.action == "accept" else None

    def _temporal_summary_overrides(
        self,
        *,
        selection: TemporalEvidenceSelection,
        evidence_pack: TemporalEvidencePack,
        generation: TemporalGenerationResult,
        summary_category: str,
        period_start: float,
        period_end: float,
    ) -> dict[str, Any]:
        summary_overrides: dict[str, Any] = {
            "summary_id": f"summary_{uuid.uuid4().hex}",
            "summary_type": "temporal",
            "summary_category": summary_category,
            "period_start": float(period_start),
            "period_end": float(period_end),
            "key_topics": [],
            "key_entities": [],
            "sentiment_summary": None,
            "change_and_pattern": None,
            "source_event_ids": list(evidence_pack.source_event_ids),
            "source_event_count": int(evidence_pack.source_event_count),
            "importance_aggregate": evidence_pack.importance_aggregate or 0.0,
            "event_type_distribution": dict(evidence_pack.event_type_distribution),
            "generated_by_model": "rule-summary" if generation.used_fallback else "temporal-llm",
            "generation_prompt": None,
            "generation_reason": f"temporal:{summary_category}",
            "evidence_selection": {
                "window_event_count": int(selection.source_event_total),
                "selected_event_count": int(evidence_pack.source_event_count),
                "omitted_event_count": int(selection.omitted_event_count),
                "source_distribution": dict(selection.source_distribution),
                "selection_policy": dict(selection.selection_policy),
            },
        }
        summary_overrides.update(generation.summary_overrides)
        return summary_overrides

    async def _attach_temporal_summary_context(self, pack: Any) -> None:
        category = str(pack.summary_category)
        previous_limit = _PREVIOUS_PERIOD_CONTEXT_LIMITS.get(category, 0)
        if previous_limit:
            pack.previous_period_summaries = await self._list_previous_temporal_context(
                summary_category=category,
                before=float(pack.period_start),
                limit=previous_limit,
            )
        child_categories = _CHILD_PERIOD_CONTEXT_CATEGORIES.get(category, [])
        if child_categories:
            child_limit = _CHILD_PERIOD_CONTEXT_LIMIT_BY_PARENT.get(
                category, _CHILD_PERIOD_CONTEXT_LIMIT_DEFAULT
            )
            pack.child_period_summaries = await self._list_child_temporal_context(
                summary_categories=child_categories,
                period_start=float(pack.period_start),
                period_end=float(pack.period_end),
                limit=child_limit,
            )

    async def _list_previous_temporal_context(
        self,
        *,
        summary_category: str,
        before: float,
        limit: int,
    ) -> list[dict[str, object]]:
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM summaries
                WHERE summary_type = 'temporal'
                  AND summary_category = ?
                  AND period_end <= ?
                ORDER BY period_end DESC, updated_at DESC
                LIMIT ?
                """,
                (summary_category, float(before), int(limit)),
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._summary_context_item(self._row_to_dict(row)) for row in rows]

    async def _list_child_temporal_context(
        self,
        *,
        summary_categories: list[str],
        period_start: float,
        period_end: float,
        limit: int,
    ) -> list[dict[str, object]]:
        normalized = [
            str(category).strip() for category in summary_categories if str(category).strip()
        ]
        if not normalized:
            return []
        await self.initialize()
        placeholders = ", ".join("?" for _ in normalized)
        args: list[object] = [*normalized, float(period_start), float(period_end), int(limit)]
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"""
                SELECT * FROM summaries
                WHERE summary_type = 'temporal'
                  AND summary_category IN ({placeholders})
                  AND period_end >= ?
                  AND period_start <= ?
                ORDER BY period_start ASC, period_end ASC, updated_at DESC
                LIMIT ?
                """,
                tuple(args),
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._summary_context_item(self._row_to_dict(row)) for row in rows]

    def _summary_context_item(self, summary: dict[str, Any]) -> dict[str, object]:
        item: dict[str, object] = {
            "summary_id": str(summary.get("summary_id") or ""),
            "summary_category": str(summary.get("summary_category") or ""),
            "period_start": float(summary.get("period_start") or 0.0),
            "period_end": float(summary.get("period_end") or 0.0),
            "content": str(summary.get("content") or ""),
            "generated_by_model": str(summary.get("generated_by_model") or ""),
        }
        key_topics = summary.get("key_topics")
        if isinstance(key_topics, list) and key_topics:
            item["key_topics"] = [str(topic) for topic in key_topics[:6] if str(topic).strip()]
        change_and_pattern = summary.get("change_and_pattern")
        if isinstance(change_and_pattern, dict) and change_and_pattern:
            item["change_and_pattern"] = change_and_pattern
        return item

    async def generate_thematic_summary(
        self,
        *,
        l1_store: L1EventStore,
        topic: str,
        period_start: float | None = None,
        period_end: float | None = None,
        min_source_count: int = 2,
    ) -> Optional[Dict[str, Any]]:
        """Build a topic-oriented thematic summary from eligible L1 events."""
        await self.initialize()
        normalized_topic = str(topic).strip().lower()
        if not normalized_topic:
            return None

        topic_events = await self._query_thematic_topic_events(
            l1_store=l1_store,
            normalized_topic=normalized_topic,
            period_start=period_start,
            period_end=period_end,
        )
        if len(topic_events) < max(1, int(min_source_count)):
            return None

        evidence_pack = self._topic_llm_service.build_evidence_pack(
            topic=topic,
            events=topic_events,
        )
        source_event_ids = list(evidence_pack.source_event_ids)
        generation = await self._generate_accepted_topic_candidate(
            evidence_pack=evidence_pack,
            topic_events=topic_events,
            fallback_summary=_topic_fallback_summary(
                topic=topic,
                source_event_count=len(source_event_ids),
                topic_events=topic_events,
            ),
        )
        if generation is None:
            return None

        summary = await self.upsert_candidate(
            candidate=generation.candidate,
            summary_overrides=self._thematic_summary_overrides(
                topic=topic,
                normalized_topic=normalized_topic,
                period_start=period_start,
                period_end=period_end,
                topic_events=topic_events,
                source_event_ids=source_event_ids,
                evidence_pack=evidence_pack,
                generation=generation,
            ),
        )
        return summary

    async def _query_thematic_topic_events(
        self,
        *,
        l1_store: L1EventStore,
        normalized_topic: str,
        period_start: float | None,
        period_end: float | None,
    ) -> list[dict[str, Any]]:
        candidates = await l1_store.query_events(
            start_time=period_start,
            end_time=period_end,
            cognition_eligible=True,
            limit=500,
        )
        return [
            event
            for event in candidates
            if event["memory_domain"] != "runtime_telemetry"
            and event["retention_class"] != "disposable"
            and normalized_topic in str(event.get("content") or "").lower()
        ]

    async def _generate_accepted_topic_candidate(
        self,
        *,
        evidence_pack: ThematicEvidencePack,
        topic_events: list[dict[str, Any]],
        fallback_summary: str,
    ) -> ThematicGenerationResult | None:
        generation = await self._topic_llm_service.generate_topic_candidate(
            evidence_pack,
            fallback_summary=fallback_summary,
        )
        decision = validate_candidate(generation.candidate, evidence_events=topic_events)
        if decision.action != "accept" and not generation.used_fallback:
            generation = self._topic_llm_service._build_fallback_result(
                evidence_pack,
                fallback_summary,
            )
            decision = validate_candidate(generation.candidate, evidence_events=topic_events)
        return generation if decision.action == "accept" else None

    def _thematic_summary_overrides(
        self,
        *,
        topic: str,
        normalized_topic: str,
        period_start: float | None,
        period_end: float | None,
        topic_events: list[dict[str, Any]],
        source_event_ids: list[str],
        evidence_pack: ThematicEvidencePack,
        generation: ThematicGenerationResult,
    ) -> dict[str, Any]:
        timestamps = _event_timestamps(topic_events)
        summary_overrides = {
            "summary_id": f"summary_{uuid.uuid4().hex}",
            "summary_type": "thematic",
            "summary_category": "topic",
            "period_start": _summary_period_start(period_start, timestamps),
            "period_end": _summary_period_end(period_end, timestamps),
            "key_topics": [str(topic).strip()],
            "key_entities": [],
            "sentiment_summary": None,
            "change_and_pattern": None,
            "source_event_ids": source_event_ids,
            "source_event_count": len(source_event_ids),
            "importance_aggregate": evidence_pack.importance_aggregate or 0.0,
            "event_type_distribution": dict(evidence_pack.event_type_distribution),
            "generated_by_model": "rule-summary" if generation.used_fallback else "topic-llm",
            "generation_prompt": None,
            "generation_reason": f"thematic:topic:{normalized_topic}",
            **generation.summary_overrides,
        }
        if not summary_overrides.get("key_topics"):
            summary_overrides["key_topics"] = [str(topic).strip()]
        return summary_overrides

    async def generate_episodic_summary(
        self,
        *,
        l1_store: L1EventStore,
        episode: Dict[str, Any],
        episode_event_ids: List[str],
    ) -> Optional[Dict[str, Any]]:
        """Build an L3 'episodic' thematic summary for one L2 episode.

        Args:
            l1_store: shared L1 event store to resolve event_id → row.
            episode: episode dict (must include episode_id, episode_type,
                time_start, time_end, primary_entity_ids, primary_topic_keys).
            episode_event_ids: list of L1 event IDs that belong to the episode
                (typically from l2.list_episode_events).
        """
        await self.initialize()
        episode_id = str(episode.get("episode_id") or "").strip()
        if not episode_id:
            return None
        if not episode_event_ids:
            return None

        # Resolve each event_id to its full L1 row. Skip missing.
        events: list[Dict[str, Any]] = []
        for event_id in episode_event_ids:
            row = await l1_store.get_event(event_id)
            if row is not None:
                events.append(row)
        if not events:
            return None

        pack = self._episodic_llm_service.build_episodic_evidence_pack(
            episode=episode,
            events=events,
        )

        # Build deterministic fallback strings.
        primary_entity_label = ", ".join(str(e) for e in pack.primary_entity_ids[:3]) or "活动"
        fallback_label = primary_entity_label[:16]
        snippets = [e.content for e in pack.events[:2] if e.content]
        joined = "；".join(snippets)
        fallback_content = (joined or f"持续 {len(pack.events)} 个事件的活动片段")[:200]

        generation = await self._episodic_llm_service.generate_episodic_candidate(
            pack,
            fallback_label=fallback_label,
            fallback_content=fallback_content,
        )

        summary = await self.upsert_candidate(
            candidate=generation.candidate,
            summary_overrides={
                "summary_id": f"summary_{uuid.uuid4().hex}",
                "summary_type": "thematic",
                "summary_category": "episodic",
                "period_start": pack.time_start,
                "period_end": pack.time_end,
                "generated_by_model": (
                    "rule-summary" if generation.used_fallback else "episodic-llm"
                ),
            },
        )
        return summary

    async def generate_missing_episodic_summaries(
        self,
        *,
        l1_store: L1EventStore,
        l2_store: Any,
        episode_ids: List[str],
    ) -> Dict[str, Any]:
        """Eagerly generate L3 episodic summaries for episodes that lack one.

        For each ``episode_id``: skip if an episodic summary already exists
        (dedup; back-writing label/summary onto the episode row when the row
        is still empty), resolve the episode + its event memberships from L2,
        then call
        :meth:`generate_episodic_summary` (configured summary model, no extended
        thinking). Newly generated summaries are back-written onto the episode
        row (``label`` / ``summary``) and its FTS entry so the episode surface
        and 经历 page search can see them. Generation failures are captured
        per-episode and never raised,
        so one bad episode does not block the rest.

        This is the caller-side seam for eager summary generation: callers that
        hold L3/L1/L2 handles (the manual ``/reconsolidate`` route and the L2
        maintenance scheduler) invoke this after consolidation. Keeping it on L3
        preserves L2-purity — ``episode_formation`` must not depend on L3.

        Returns ``{"generated": int, "errors": list[str]}``.
        """
        generated = 0
        errors: List[str] = []
        seen: set[str] = set()
        for raw_id in episode_ids:
            episode_id = str(raw_id or "").strip()
            if not episode_id or episode_id in seen:
                continue
            seen.add(episode_id)
            try:
                episode = await l2_store.get_episode(episode_id=episode_id)
                if episode is None:
                    continue
                existing = await self.get_episodic_summary_by_episode_id(episode_id)
                if existing is not None:
                    # Backfill episodes summarized before back-writing existed.
                    if episode_needs_summary_backfill(episode):
                        await backwrite_episode_summary(
                            l2_store,
                            episode=episode,
                            summary=existing,
                        )
                    continue
                event_links = await l2_store.list_episode_events(episode_id=episode_id)
                event_ids = [
                    str(link.get("event_id") or "").strip()
                    for link in event_links
                    if link.get("event_id")
                ]
                if not event_ids:
                    continue
                summary = await self.generate_episodic_summary(
                    l1_store=l1_store,
                    episode=episode,
                    episode_event_ids=event_ids,
                )
                if summary is not None:
                    await backwrite_episode_summary(
                        l2_store,
                        episode=episode,
                        summary=summary,
                    )
                generated += 1
            except Exception as exc:  # non-blocking: log + continue
                logger.warning(
                    "Eager episodic summary generation failed for %s: %s",
                    episode_id,
                    exc,
                )
                errors.append(f"{episode_id}: {exc}")
        return {"generated": generated, "errors": errors}

    async def generate_experience_summary(
        self,
        *,
        l1_store: L1EventStore,
        l2_store: Any,
        experience: Dict[str, Any],
        experience_members: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Build an L3 episodic review for one L2 experience."""
        await self.initialize()
        context = await self._build_experience_summary_context(
            l1_store=l1_store,
            l2_store=l2_store,
            experience=experience,
            experience_members=experience_members,
        )
        if context is None:
            return None

        draft = await self._generate_experience_summary_draft(
            experience=experience,
            context=context,
        )
        candidate = self._build_experience_summary_candidate(
            context=context,
            draft=draft,
        )
        return await self.upsert_candidate(
            candidate=candidate,
            summary_overrides=self._experience_summary_overrides(
                context=context,
                used_fallback=draft.used_fallback,
            ),
        )

    async def _build_experience_summary_context(
        self,
        *,
        l1_store: L1EventStore,
        l2_store: Any,
        experience: Dict[str, Any],
        experience_members: List[Dict[str, Any]],
    ) -> _ExperienceSummaryContext | None:
        experience_id = str(experience.get("experience_id") or "").strip()
        if not experience_id:
            return None

        episode_ids, event_ids = await self._collect_experience_member_event_ids(
            l2_store=l2_store,
            experience_members=experience_members,
        )
        if not event_ids:
            return None

        events = await self._load_experience_events(l1_store=l1_store, event_ids=event_ids)
        fallback_label = _experience_fallback_label(experience, events)
        fallback_content = _experience_fallback_content(
            experience,
            events,
            len(event_ids),
        )
        period_start, period_end = self._experience_summary_period(
            experience=experience,
            events=events,
        )

        return _ExperienceSummaryContext(
            experience_id=experience_id,
            episode_ids=episode_ids,
            event_ids=event_ids,
            events=events,
            fallback_label=fallback_label,
            fallback_content=fallback_content,
            period_start=period_start,
            period_end=period_end,
        )

    async def _collect_experience_member_event_ids(
        self,
        *,
        l2_store: Any,
        experience_members: List[Dict[str, Any]],
    ) -> tuple[list[str], list[str]]:
        episode_ids: list[str] = []
        event_ids: list[str] = []
        seen_events: set[str] = set()
        for member in experience_members:
            if str(member.get("role") or "") == "excluded":
                continue
            member_type = str(member.get("member_type") or "")
            member_id = str(member.get("member_id") or "").strip()
            if not member_id:
                continue
            if member_type == "episode":
                episode_ids.append(member_id)
                for link in await l2_store.list_episode_events(episode_id=member_id):
                    event_id = str(link.get("event_id") or "").strip()
                    if event_id and event_id not in seen_events:
                        seen_events.add(event_id)
                        event_ids.append(event_id)
            elif member_type == "event" and member_id not in seen_events:
                seen_events.add(member_id)
                event_ids.append(member_id)
        return episode_ids, event_ids

    async def _load_experience_events(
        self,
        *,
        l1_store: L1EventStore,
        event_ids: list[str],
    ) -> list[Dict[str, Any]]:
        events: list[Dict[str, Any]] = []
        for event_id in event_ids:
            row = await l1_store.get_event(event_id)
            if row is not None:
                events.append(row)
        return events

    def _experience_summary_period(
        self,
        *,
        experience: Dict[str, Any],
        events: list[Dict[str, Any]],
    ) -> tuple[float, float]:
        timestamps = [
            float(event["timestamp"]) for event in events if event.get("timestamp") is not None
        ]
        period_start = float(
            experience.get("time_start") or (min(timestamps) if timestamps else time.time())
        )
        period_end = float(
            experience.get("time_end") or (max(timestamps) if timestamps else period_start)
        )
        return period_start, period_end

    async def _generate_experience_summary_draft(
        self,
        *,
        experience: Dict[str, Any],
        context: _ExperienceSummaryContext,
    ) -> _ExperienceSummaryDraft:
        if not context.events:
            return _ExperienceSummaryDraft(
                content=context.fallback_content,
                source_event_ids=list(context.event_ids),
                metadata={"fallback": True},
                used_fallback=True,
            )

        pack = self._episodic_llm_service.build_episodic_evidence_pack(
            episode=self._experience_summary_episode_payload(
                experience=experience,
                context=context,
            ),
            events=context.events,
        )
        generation = await self._episodic_llm_service.generate_episodic_candidate(
            pack,
            fallback_label=context.fallback_label,
            fallback_content=context.fallback_content,
        )
        return _ExperienceSummaryDraft(
            content=str(generation.candidate.content or "").strip(),
            source_event_ids=list(generation.candidate.source_event_ids),
            metadata=dict(generation.candidate.insight_metadata),
            used_fallback=generation.used_fallback,
        )

    def _build_experience_summary_candidate(
        self,
        *,
        context: _ExperienceSummaryContext,
        draft: _ExperienceSummaryDraft,
    ) -> L3Candidate:
        content = draft.content
        if (
            not content
            or _is_generic_experience_text(content)
            or _is_placeholder_experience_text(content)
        ):
            content = context.fallback_content

        metadata = dict(draft.metadata)
        metadata.pop("source_episode_id", None)
        metadata["source_experience_id"] = context.experience_id
        metadata["source_episode_ids"] = list(context.episode_ids)
        if not _experience_text_is_usable(metadata.get("label")):
            metadata["label"] = context.fallback_label
        else:
            metadata["label"] = str(metadata["label"]).strip()[:36]

        return L3Candidate(
            content=content,
            source_event_ids=draft.source_event_ids or context.event_ids,
            summary_category="episodic",
            summary_type="thematic",
            insight_key=f"experience:{context.experience_id}:review",
            insight_metadata=metadata,
        )

    def _experience_summary_episode_payload(
        self,
        *,
        experience: Dict[str, Any],
        context: _ExperienceSummaryContext,
    ) -> Dict[str, Any]:
        return {
            "episode_id": context.experience_id,
            "episode_type": experience.get("experience_type") or "experience",
            "time_start": context.period_start,
            "time_end": context.period_end,
            "primary_entity_ids": experience.get("primary_entity_ids") or [],
            "primary_topic_keys": experience.get("primary_topic_keys") or [],
        }

    def _experience_summary_overrides(
        self,
        *,
        context: _ExperienceSummaryContext,
        used_fallback: bool,
    ) -> Dict[str, Any]:
        return {
            "summary_id": f"summary_{uuid.uuid4().hex}",
            "summary_type": "thematic",
            "summary_category": "episodic",
            "period_start": context.period_start,
            "period_end": context.period_end,
            "generated_by_model": "rule-summary" if used_fallback else "episodic-llm",
            "generation_reason": "experience:episodic",
        }

    def get_statistics(self) -> Dict[str, Any]:
        """Return lightweight metadata for reporting."""
        return {
            "db_path": self.db_path,
            "vector_enabled": self._vectors_enabled(),
            "async_embeddings": self._async_embeddings_enabled(),
            "embedding_queue_size": (
                self._embedding_queue.qsize() if self._embedding_queue is not None else 0
            ),
            "embedding_active_count": int(getattr(self, "_embedding_active_count", 0)),
            "embedding_worker_running": bool(
                self._embedding_worker is not None and not self._embedding_worker.done()
            ),
        }


__all__ = ["L3SummaryStore"]
