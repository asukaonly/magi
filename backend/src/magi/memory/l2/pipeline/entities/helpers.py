"""Pure helper methods for L2 pipeline entity resolution."""

from __future__ import annotations

from typing import Any, Protocol, cast

from ....event_contracts import MemoryEvent
from ...models import L2FocalEntityRef, ResolvedEntityMention


class _EntityResolutionHelperHostProtocol(Protocol):
    _entity_catalog: Any | None

    def _normalize_entity_type(self, raw_value: Any) -> str | None: ...


class L2EntityResolutionHelperMixin:
    """Shared entity quality, merge, and focal-entity helpers."""

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

    async def _enrich_resolution_candidates(self, candidates: list[dict]) -> list[dict]:
        """Read bounded original context; historical context is never new evidence."""
        l1_store = getattr(self, "_l1_store", None)
        for item in candidates:
            evidence = []
            if l1_store is not None:
                for event_id in item.get("evidence_event_ids", [])[:3]:
                    event = await l1_store.get_event(str(event_id))
                    if event is not None:
                        content = str(event.get("content") or "").strip()
                        if content:
                            evidence.append(content[:500])
            item["identity_evidence"] = evidence
        return candidates

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

    async def _derive_place_and_topic_hints(
        self, touched_entity_ids: list[str]
    ) -> tuple[list[str], list[str]]:
        """Resolve current catalog types instead of interpreting ID prefixes."""
        host = self._entity_helper_host()
        if host._entity_catalog is None or not touched_entity_ids:
            return [], []
        rows = await host._entity_catalog.list_entities(entity_ids=touched_entity_ids, limit=None)
        return (
            sorted(row["entity_id"] for row in rows if row["entity_type"] == "place"),
            sorted(row["entity_id"] for row in rows if row["entity_type"] == "topic"),
        )

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
