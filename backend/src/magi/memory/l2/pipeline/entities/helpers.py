"""Pure helper methods for L2 pipeline entity resolution."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Protocol, cast

from ....event_contracts import MemoryEvent
from ...models import L2FocalEntityRef, ResolvedEntityMention


class _EntityResolutionHelperHostProtocol(Protocol):
    _entity_catalog: Any | None

    def _normalize_entity_type(self, raw_value: Any) -> str | None: ...


class L2EntityResolutionHelperMixin:
    """Shared entity quality, merge, and focal-entity helpers."""

    _GENERIC_PLATFORM_NAMES: frozenset[str] = frozenset(
        {
            "youtube",
            "google",
            "github",
            "bilibili",
            "哔哩哔哩",
            "b站",
            "douyin",
            "抖音",
            "tiktok",
            "tiktok china",
            "zhihu",
            "知乎",
            "weibo",
            "微博",
            "twitter",
            "x",
            "reddit",
            "medium",
            "stackoverflow",
            "stack overflow",
            "wikipedia",
            "spotify",
            "netflix",
            "twitch",
            "taobao",
            "淘宝",
            "jd",
            "京东",
            "xiaohongshu",
            "小红书",
            "last.fm",
            "facebook",
            "instagram",
            "linkedin",
            "baidu",
            "百度",
            "bing",
            "yahoo",
        }
    )

    _NAME_NOISE_PATTERNS: re.Pattern = re.compile(
        r"[\w.+-]+@[\w.-]+\.\w{2,}"  # email
        r"|(\d{1,3}\.){3}\d{1,3}"  # IPv4
        r"|^(Home|Inbox|Schema Panel|Import Panel|Verification Code|"
        r"Sign in|Log in|Welcome|Error|404|Loading)$",
        re.IGNORECASE,
    )
    _SENTENCE_PUNCT: re.Pattern = re.compile(r"[！？。，、；]")
    _MAX_ENTITY_NAME_WIDTH = 50
    _MERGEABLE_TYPE_GROUPS: list[frozenset[str]] = [
        frozenset({"software", "product", "technology", "organization", "activity"}),
        frozenset({"media", "activity", "topic", "concept"}),
        frozenset({"person", "group"}),
        frozenset({"place", "location_state"}),
    ]

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
        if entity_type != "software" and alias_cf in self._GENERIC_PLATFORM_NAMES:
            return False
        if len(canonical_cf) > 8 and len(alias_cf) <= 3:
            return False
        return True

    @classmethod
    def _display_width(cls, text: str) -> int:
        """East-Asian-aware display width (CJK chars count as 2)."""
        return sum(2 if unicodedata.east_asian_width(char) in ("W", "F") else 1 for char in text)

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
        alpha_count = sum(1 for char in text if char.isalpha())
        if alpha_count == 0:
            return False
        if len(cls._SENTENCE_PUNCT.findall(text)) >= 2:
            return False
        return True

    async def _build_catalog_name_index(self) -> dict[str, str]:
        """Build casefold(name/alias/id) -> entity_id lookup from the catalog."""
        host = self._entity_helper_host()
        if host._entity_catalog is None:
            return {}
        entities = await host._entity_catalog.list_entities(limit=None)
        index: dict[str, str] = {}
        ambiguous: set[str] = set()

        def add_key(raw_value: object, entity_id: str) -> None:
            key = str(raw_value or "").strip().casefold()
            if key in ambiguous:
                return
            if key in index and index[key] != entity_id:
                index.pop(key)
                ambiguous.add(key)
            elif key and entity_id:
                index[key] = entity_id

        for entity in entities:
            name = str(entity.get("canonical_name", "")).strip().casefold()
            entity_id = str(entity.get("entity_id", ""))
            add_key(entity_id, entity_id)
            add_key(name, entity_id)
            for alias in entity.get("aliases", []) or []:
                add_key(alias, entity_id)
        return index

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
        host = self._entity_helper_host()
        focal_entities: list[L2FocalEntityRef] = []
        self_entity_id = self._resolve_self_entity_id(event)
        if self_entity_id:
            focal_entities.append(L2FocalEntityRef(entity_id=self_entity_id, entity_type="user"))
        seen = {item.entity_id for item in focal_entities}
        for mention in resolved_mentions:
            entity_id = mention.resolved_entity_id
            entity_type = host._normalize_entity_type(mention.entity_type)
            if not entity_id or not entity_type or entity_id in seen:
                continue
            focal_entities.append(
                L2FocalEntityRef(entity_id=str(entity_id), entity_type=entity_type)
            )
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

    def _derive_place_and_topic_hints(
        self,
        touched_entity_ids: list[str],
    ) -> tuple[list[str], list[str]]:
        """Split touched entity ids into place + topic hints for episode formation.

        Entity ids are formatted ``{entity_type}:{slug}`` (see
        ``_build_canonical_entity_id``), so the catalog type is recoverable from
        the id prefix. The episode worker passes these through to
        ``EpisodeCandidateJob`` (``place_ids`` / ``topic_keys``) so multi-type gap
        + topic matching in ``episode_formation`` can fire instead of collapsing
        every batch into a 30-min activity bucket.

        Returns ``(place_ids, topic_keys)`` — both deduped and sorted:
        - ``place_ids``: touched entities whose ``entity_type == "place"``.
        - ``topic_keys``: touched entities whose ``entity_type == "topic"``.
        """
        place_ids: set[str] = set()
        topic_keys: set[str] = set()
        for raw in touched_entity_ids:
            entity_id = str(raw).strip()
            if not entity_id:
                continue
            entity_type, _, _ = entity_id.partition(":")
            if entity_type == "place":
                place_ids.add(entity_id)
            elif entity_type == "topic":
                topic_keys.add(entity_id)
        return sorted(place_ids), sorted(topic_keys)

    def _resolve_self_entity_id(self, event: MemoryEvent) -> str | None:
        if event.user_id:
            raw = str(event.user_id).strip()
            if not raw:
                return None
            # Phase H+2 identity layer: ingress now canonicalizes user_id
            # before it reaches L1/L2 (see docs/identity-architecture.md).
            # The ``startswith("channel_")`` branch below is therefore
            # unreachable in healthy state — kept as a defensive
            # belt-and-suspenders for legacy ``channel_*`` rows that
            # haven't been touched by the data-migration script yet
            # (Phase 1). ``"self"`` literal stays because the L2 prompt
            # explicitly emits it (see prompts/__init__.py:104, 282, 428).
            if raw == "self" or raw.startswith("channel_"):
                return "user:local_user"
            return f"user:{raw}"
        return None

    def _entity_helper_host(self) -> _EntityResolutionHelperHostProtocol:
        return cast(_EntityResolutionHelperHostProtocol, self)


__all__ = ["L2EntityResolutionHelperMixin"]
