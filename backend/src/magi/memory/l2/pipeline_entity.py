"""Entity resolution methods for L2Pipeline."""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING, Any, Optional

from ...core.logger import get_logger
from ..event_contracts import MemoryEvent
from .models import (
    L2EntityCandidate,
    L2EntityResolutionMention,
    L2FocalEntityRef,
    L2Phase1Result,
    ResolvedEntityMention,
)

if TYPE_CHECKING:
    from .entity_catalog import L2EntityCatalog
    from .llm_service import L2LLMService

logger = get_logger(__name__)


class L2EntityResolutionMixin:
    """Mixin providing entity resolution methods for L2Pipeline."""

    # These attributes are provided by L2Pipeline at runtime.
    _entity_catalog: Optional[L2EntityCatalog]
    _llm_service: Optional[L2LLMService]

    async def _resolve_phase1_entities(
        self,
        event: MemoryEvent,
        phase1_result: L2Phase1Result,
        *,
        evidence_event_ids: list[str],
        allowed_entity_types: frozenset[str] | None = None,
    ) -> list[ResolvedEntityMention]:
        """Register Phase 1 entities in the entity catalog and return resolved mentions."""
        if self._entity_catalog is None:
            return []

        resolved_mentions: list[ResolvedEntityMention] = []
        for entity in phase1_result.entities:
            if not entity.surface:
                continue
            mention_text = entity.surface
            normalized_surface = entity.normalized_name or mention_text
            entity_type = self._normalize_entity_type(entity.entity_type)  # type: ignore[attr-defined]
            if allowed_entity_types and entity_type not in allowed_entity_types:
                logger.debug(
                    "L2 Phase 1 entity filtered by profile",
                    mention_text=mention_text,
                    entity_type=entity_type,
                    event_id=event.event_id,
                )
                continue
            if not self._is_quality_entity_name(normalized_surface):
                logger.debug(
                    "L2 Phase 1 entity filtered by name quality",
                    mention_text=mention_text,
                    entity_type=entity_type,
                    event_id=event.event_id,
                )
                continue
            mention_confidence = entity.confidence

            # If Phase 1 already resolved the entity to an existing ID, use it
            resolved_entity_id: str | None = entity.resolved_id
            resolved_confidence: float | None = entity.confidence if entity.resolved_id else None

            # If not resolved by Phase 1, try catalog alias resolution then LLM resolution
            if not resolved_entity_id:
                resolved_entity_id, resolved_confidence = await self._resolve_entity_id(
                    mention={"mention_text": mention_text, "canonical_name_hint": normalized_surface, "alias_signals": entity.alias_signals},
                    entity_type=entity_type,
                    mention_text=mention_text,
                    mention_confidence=mention_confidence,
                    event=event,
                )

            # Ensure the entity exists in the catalog before recording the mention (FK constraint)
            if resolved_entity_id:
                await self._entity_catalog.upsert_entity(
                    canonical_name=normalized_surface,
                    entity_type=entity_type,
                    entity_id=resolved_entity_id,
                )

            await self._entity_catalog.record_mention(
                mention_text=mention_text,
                normalized_surface=normalized_surface,
                entity_type=entity_type,
                evidence_event_ids=list(evidence_event_ids),
                evidence_text=mention_text,
                resolved_entity_id=resolved_entity_id,
                confidence=resolved_confidence,
            )
            resolved_mentions.append(
                ResolvedEntityMention(
                    mention_text=mention_text,
                    normalized_surface=normalized_surface,
                    entity_type=entity_type,
                    resolved_entity_id=resolved_entity_id,
                    confidence=resolved_confidence,
                )
            )
        return resolved_mentions

    async def _resolve_mentions(
        self,
        event: MemoryEvent,
        mentions: list[dict[str, Any]],
        *,
        evidence_event_ids: list[str] | None = None,
    ) -> list[ResolvedEntityMention]:
        if self._entity_catalog is None:
            return []

        resolved_mentions: list[ResolvedEntityMention] = []
        for mention in mentions:
            if not isinstance(mention, dict):
                continue

            mention_text = str(mention.get("mention_text", "")).strip()
            if not mention_text:
                continue
            normalized_surface = str(mention.get("normalized_surface") or mention_text).strip()
            entity_type = self._normalize_entity_type(mention.get("entity_type"))  # type: ignore[attr-defined]
            evidence_text = self._non_empty_text(mention.get("evidence_text")) or event.content  # type: ignore[attr-defined]
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
                evidence_event_ids=list(evidence_event_ids or [event.event_id]),
                evidence_text=evidence_text,
                resolved_entity_id=resolved_entity_id,
                confidence=resolved_confidence,
            )
            resolved_mentions.append(
                ResolvedEntityMention(
                    mention_text=mention_text,
                    normalized_surface=normalized_surface,
                    entity_type=entity_type,
                    resolved_entity_id=resolved_entity_id,
                    confidence=resolved_confidence,
                )
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

        # 1. Type-scoped alias resolution
        alias_resolution = await self._entity_catalog.resolve_alias(
            mention_text,
            entity_type=entity_type,
        )
        if alias_resolution.get("decision") == "match":
            return (str(alias_resolution["entity_id"]), float(alias_resolution["matched_confidence"]))

        # 2. Cross-type alias resolution: find same-name entity under a compatible type
        if entity_type:
            cross_type_resolution = await self._entity_catalog.resolve_alias(
                mention_text,
                entity_type=None,
            )
            if cross_type_resolution.get("decision") == "match":
                matched_id = str(cross_type_resolution["entity_id"])
                matched_type = matched_id.split(":", 1)[0] if ":" in matched_id else ""
                if self._are_types_mergeable(entity_type, matched_type):
                    logger.debug(
                        "L2 cross-type entity resolved",
                        mention_text=mention_text,
                        requested_type=entity_type,
                        matched_type=matched_type,
                        matched_entity_id=matched_id,
                    )
                    return (matched_id, float(cross_type_resolution["matched_confidence"]))

        # 3. LLM-based resolution against same-type candidates
        if self._llm_service is not None and entity_type:
            candidate_entities = await self._entity_catalog.list_entities_by_type(entity_type=entity_type, limit=20)
            if candidate_entities:
                llm_resolution = await self._llm_service.resolve_entity(
                    mention=L2EntityResolutionMention(
                        mention_text=mention_text,
                        entity_type=entity_type,
                        context_text=event.content,
                    ),
                    candidate_entities=[L2EntityCandidate.from_dict(item) for item in candidate_entities],
                )
                if llm_resolution.decision == "match" and llm_resolution.matched_entity_id:
                    return (
                        str(llm_resolution.matched_entity_id),
                        float(llm_resolution.confidence or mention_confidence),
                    )

        canonical_name = self._non_empty_text(mention.get("canonical_name_hint")) or mention_text  # type: ignore[attr-defined]
        if not entity_type or mention_confidence < 0.9:
            return (None, mention_confidence if mention_confidence > 0.0 else None)

        # 4. Same-name catalog dedup: reuse existing entity if name already registered
        existing_by_name = await self._entity_catalog.find_by_canonical_name(canonical_name)
        if existing_by_name:
            for existing in existing_by_name:
                existing_type = str(existing.get("entity_type", ""))
                if existing_type == entity_type or self._are_types_mergeable(entity_type, existing_type):
                    matched_id = str(existing["entity_id"])
                    logger.debug(
                        "L2 entity dedup: reusing existing same-name entity",
                        mention_text=mention_text,
                        canonical_name=canonical_name,
                        requested_type=entity_type,
                        existing_type=existing_type,
                        entity_id=matched_id,
                    )
                    await self._entity_catalog.add_alias(
                        entity_id=matched_id,
                        alias_text=mention_text,
                        confidence=min(max(mention_confidence, 0.9), 0.99),
                    )
                    return (matched_id, mention_confidence)

        entity_id = self._build_canonical_entity_id(entity_type=entity_type, canonical_name=canonical_name)  # type: ignore[attr-defined]
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
            alias_text = self._non_empty_text(alias)  # type: ignore[attr-defined]
            if not alias_text:
                continue
            if not self._is_valid_alias(alias_text, canonical_name, entity_type):
                logger.debug(
                    "L2 alias rejected by validation",
                    alias_text=alias_text,
                    canonical_name=canonical_name,
                    entity_type=entity_type,
                    entity_id=entity_id,
                )
                continue
            await self._entity_catalog.add_alias(
                entity_id=entity_id,
                alias_text=alias_text,
                confidence=min(max(mention_confidence, 0.85), 0.95),
            )
        return (entity_id, mention_confidence)

    _GENERIC_PLATFORM_NAMES: frozenset[str] = frozenset({
        "youtube", "google", "github", "bilibili", "哔哩哔哩", "b站",
        "douyin", "抖音", "tiktok", "tiktok china",
        "zhihu", "知乎", "weibo", "微博",
        "twitter", "x", "reddit", "medium",
        "stackoverflow", "stack overflow", "wikipedia",
        "spotify", "netflix", "twitch",
        "taobao", "淘宝", "jd", "京东",
        "xiaohongshu", "小红书",
        "last.fm", "facebook", "instagram", "linkedin",
        "baidu", "百度", "bing", "yahoo",
    })

    def _is_valid_alias(
        self,
        alias_text: str,
        canonical_name: str,
        entity_type: str,
    ) -> bool:
        """Check whether an alias is semantically valid for the given entity."""
        alias_cf = alias_text.casefold().strip()
        canonical_cf = canonical_name.casefold().strip()
        if alias_cf == canonical_cf:
            return True
        # Reject generic platform names as aliases for non-software entities
        if entity_type != "software" and alias_cf in self._GENERIC_PLATFORM_NAMES:
            return False
        # Reject aliases that are too short relative to a long canonical name
        # (e.g., "抖音" as alias for "坤的真爱粉的抖音直播间")
        if len(canonical_cf) > 8 and len(alias_cf) <= 3:
            return False
        return True

    _NAME_NOISE_PATTERNS: re.Pattern = re.compile(
        r"[\w.+-]+@[\w.-]+\.\w{2,}"  # email
        r"|(\d{1,3}\.){3}\d{1,3}"     # IPv4
        r"|^(Home|Inbox|Schema Panel|Import Panel|Verification Code|"
        r"Sign in|Log in|Welcome|Error|404|Loading)$",
        re.IGNORECASE,
    )
    _SENTENCE_PUNCT: re.Pattern = re.compile(r"[！？。，、；]")
    _MAX_ENTITY_NAME_WIDTH = 50

    @classmethod
    def _display_width(cls, text: str) -> int:
        """East-Asian-aware display width (CJK chars count as 2)."""
        return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in text)

    @classmethod
    def _is_quality_entity_name(cls, name: str) -> bool:
        """Return False for names that look like noise (page titles, UI labels, etc.)."""
        text = name.strip()
        if not text or len(text) < 2:
            return False
        if cls._NAME_NOISE_PATTERNS.search(text):
            return False
        if cls._display_width(text) > cls._MAX_ENTITY_NAME_WIDTH:
            return False
        alpha_count = sum(1 for c in text if c.isalpha())
        if alpha_count == 0:
            return False
        # Reject names that look like CJK sentences (2+ sentence-ending punctuation)
        if len(cls._SENTENCE_PUNCT.findall(text)) >= 2:
            return False
        return True

    async def _build_catalog_name_index(self) -> dict[str, str]:
        """Build a casefold(canonical_name) → entity_id lookup from the catalog."""
        if self._entity_catalog is None:
            return {}
        entities = await self._entity_catalog.list_entities(limit=1000)
        index: dict[str, str] = {}
        for entity in entities:
            name = str(entity.get("canonical_name", "")).strip().casefold()
            entity_id = str(entity.get("entity_id", ""))
            if name and entity_id and name not in index:
                index[name] = entity_id
        return index

    _MERGEABLE_TYPE_GROUPS: list[frozenset[str]] = [
        frozenset({"software", "product", "technology", "organization", "activity"}),
        frozenset({"media", "activity", "topic", "concept"}),
        frozenset({"person", "group"}),
        frozenset({"place", "location_state"}),
    ]

    @classmethod
    def _are_types_mergeable(cls, type_a: str, type_b: str) -> bool:
        """Return whether two entity types are close enough to merge."""
        if type_a == type_b:
            return True
        a = type_a.strip().lower()
        b = type_b.strip().lower()
        for group in cls._MERGEABLE_TYPE_GROUPS:
            if a in group and b in group:
                return True
        return False

    def _build_focal_entities(
        self,
        event: MemoryEvent,
        resolved_mentions: list[ResolvedEntityMention],
    ) -> list[L2FocalEntityRef]:
        focal_entities: list[L2FocalEntityRef] = []
        self_entity_id = self._resolve_self_entity_id(event)
        if self_entity_id:
            focal_entities.append(L2FocalEntityRef(entity_id=self_entity_id, entity_type="user"))
        seen = {item.entity_id for item in focal_entities}
        for mention in resolved_mentions:
            entity_id = mention.resolved_entity_id
            entity_type = self._normalize_entity_type(mention.entity_type)  # type: ignore[attr-defined]
            if not entity_id or not entity_type or entity_id in seen:
                continue
            focal_entities.append(L2FocalEntityRef(entity_id=str(entity_id), entity_type=entity_type))
            seen.add(str(entity_id))
        return focal_entities

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
