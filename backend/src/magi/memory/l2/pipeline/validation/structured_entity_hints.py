"""Structured entity-hint injection for L2 extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .....core.logger import get_logger
from ....event_contracts import MemoryEvent
from ...models import L2Phase1FactClaim, L2Phase1Result, StructuredGraphHint
from .structured_hint_common import L2StructuredHintHostMixin

logger = get_logger(__name__)


@dataclass(frozen=True)
class _StructuredEntityHintCandidate:
    entity_id: str
    entity_type: str
    canonical_name: str
    alias_text: str | None = None


@dataclass
class _StructuredEntityHintUpsertState:
    catalog: Any
    host: Any
    source_event_ids: tuple[str, ...]
    seen_ids: set[str] = field(default_factory=set)
    upserted_count: int = 0


class L2StructuredEntityHintMixin(L2StructuredHintHostMixin):
    """Inject source-owned structured hints into Phase 1 context."""

    async def _upsert_structured_hint_entities(self, event: MemoryEvent) -> int:
        """Persist source-owned entity hints so graph hints can reference catalog IDs."""
        metadata_json = event.metadata_json
        if not isinstance(metadata_json, dict):
            return 0
        catalog = getattr(self, "_entity_catalog", None)
        if catalog is None:
            return 0

        state = _StructuredEntityHintUpsertState(
            catalog=catalog,
            host=self._structured_hint_host(),
            source_event_ids=(event.event_id,),
        )
        await self._upsert_structured_entity_hint_records(metadata_json, state)
        await self._upsert_structured_graph_ref_entities(metadata_json, state)

        if state.upserted_count:
            logger.debug(
                "L2 structured entity hints persisted",
                event_id=event.event_id,
                upserted_count=state.upserted_count,
            )
        return state.upserted_count

    async def _upsert_structured_entity_hint_records(
        self,
        metadata_json: dict[str, Any],
        state: _StructuredEntityHintUpsertState,
    ) -> None:
        raw_entity_hints = metadata_json.get("structured_entity_hints")
        if isinstance(raw_entity_hints, list):
            for hint in raw_entity_hints:
                candidate = self._structured_entity_hint_candidate(hint, state=state)
                if candidate is None:
                    continue
                existing_entity_id = await self._resolve_existing_structured_ref_entity_id(
                    catalog=state.catalog,
                    entity_ref=candidate.entity_id,
                    entity_type=candidate.entity_type,
                    canonical_name=candidate.canonical_name,
                )
                if existing_entity_id:
                    await state.catalog.add_alias(
                        entity_id=existing_entity_id,
                        alias_text=candidate.alias_text,
                        confidence=0.98,
                        source_event_ids=state.source_event_ids,
                    )
                    state.seen_ids.add(existing_entity_id)
                    continue
                await self._upsert_structured_hint_entity(state, candidate)

    async def _upsert_structured_graph_ref_entities(
        self,
        metadata_json: dict[str, Any],
        state: _StructuredEntityHintUpsertState,
    ) -> None:
        raw_graph_hints = metadata_json.get("structured_graph_hints")
        if isinstance(raw_graph_hints, list):
            for hint in raw_graph_hints:
                if not isinstance(hint, dict):
                    continue
                for candidate in self._structured_graph_ref_candidates(hint, state=state):
                    existing_entity_id = await self._resolve_existing_structured_ref_entity_id(
                        catalog=state.catalog,
                        entity_ref=candidate.entity_id,
                        entity_type=candidate.entity_type,
                        canonical_name=candidate.canonical_name,
                    )
                    if existing_entity_id:
                        await self._add_existing_structured_entity_alias(
                            state,
                            entity_id=existing_entity_id,
                            alias_text=candidate.alias_text,
                        )
                        continue
                    await self._upsert_structured_hint_entity(state, candidate)

    def _structured_entity_hint_candidate(
        self,
        hint: Any,
        *,
        state: _StructuredEntityHintUpsertState,
    ) -> _StructuredEntityHintCandidate | None:
        if not isinstance(hint, dict):
            return None
        mention_text = state.host._non_empty_text(hint.get("mention_text"))
        entity_type = state.host._normalize_entity_type(hint.get("entity_type"))
        if not mention_text or not entity_type:
            return None
        canonical_name = state.host._non_empty_text(hint.get("canonical_name_hint")) or mention_text
        resolved_id = state.host._non_empty_text(hint.get("resolved_entity_id"))
        entity_id = resolved_id or state.host._build_canonical_entity_id(
            entity_type=entity_type,
            canonical_name=canonical_name,
        )
        return _StructuredEntityHintCandidate(
            entity_id=entity_id,
            entity_type=entity_type,
            canonical_name=canonical_name,
            alias_text=mention_text,
        )

    def _structured_graph_ref_candidates(
        self,
        hint: dict[str, Any],
        *,
        state: _StructuredEntityHintUpsertState,
    ) -> list[_StructuredEntityHintCandidate]:
        candidates: list[_StructuredEntityHintCandidate] = []
        for ref_key, type_key in (
            ("subject_ref", "subject_type"),
            ("object_ref", "object_type"),
        ):
            entity_ref = state.host._non_empty_text(hint.get(ref_key))
            entity_type = state.host._normalize_entity_type(hint.get(type_key))
            if (
                not entity_ref
                or not entity_type
                or ":" not in entity_ref
                or entity_ref.startswith("user:")
            ):
                continue
            canonical_name = self._canonical_name_from_entity_ref(
                entity_ref=entity_ref,
                entity_type=entity_type,
            )
            candidates.append(
                _StructuredEntityHintCandidate(
                    entity_id=entity_ref,
                    entity_type=entity_type,
                    canonical_name=canonical_name,
                    alias_text=canonical_name,
                )
            )
        return candidates

    async def _upsert_structured_hint_entity(
        self,
        state: _StructuredEntityHintUpsertState,
        candidate: _StructuredEntityHintCandidate,
    ) -> None:
        if candidate.entity_id in state.seen_ids:
            return
        state.seen_ids.add(candidate.entity_id)
        normalized_entity_id = await state.catalog.upsert_entity(
            entity_id=candidate.entity_id,
            canonical_name=candidate.canonical_name,
            entity_type=candidate.entity_type,
            source_event_ids=state.source_event_ids,
        )
        state.seen_ids.add(normalized_entity_id)
        alias = state.host._non_empty_text(candidate.alias_text) or candidate.canonical_name
        if alias:
            await state.catalog.add_alias(
                entity_id=normalized_entity_id,
                alias_text=alias,
                confidence=0.98,
                source_event_ids=state.source_event_ids,
            )
        state.upserted_count += 1

    async def _add_existing_structured_entity_alias(
        self,
        state: _StructuredEntityHintUpsertState,
        *,
        entity_id: str,
        alias_text: str | None,
    ) -> None:
        alias = state.host._non_empty_text(alias_text)
        if alias:
            await state.catalog.add_alias(
                entity_id=entity_id,
                alias_text=alias,
                confidence=0.98,
                source_event_ids=state.source_event_ids,
            )
        state.seen_ids.add(entity_id)

    def _canonical_name_from_entity_ref(self, *, entity_ref: str, entity_type: str) -> str:
        _, _, suffix = entity_ref.partition(":")
        text = suffix or entity_ref
        normalized_type = str(entity_type or "").strip().casefold()
        for separator in ("-", "_", ":"):
            marker = f"{normalized_type}{separator}"
            if text.casefold().startswith(marker):
                text = text[len(marker) :]
                break
        return text.replace("_", " ").replace("-", " ").strip() or entity_ref

    async def _resolve_existing_structured_ref_entity_id(
        self,
        *,
        catalog: Any,
        entity_ref: str,
        entity_type: str,
        canonical_name: str,
    ) -> str | None:
        """Return an existing same-name entity for a structured graph ref."""
        for candidate in self._structured_ref_lookup_candidates(
            entity_ref=entity_ref,
            entity_type=entity_type,
            canonical_name=canonical_name,
        ):
            matches = await catalog.find_by_canonical_name(
                candidate,
                entity_type=entity_type,
            )
            if matches:
                return str(matches[0]["entity_id"])
        return None

    def _structured_ref_lookup_candidates(
        self,
        *,
        entity_ref: str,
        entity_type: str,
        canonical_name: str,
    ) -> list[str]:
        candidates: list[str] = []

        def add(value: str | None) -> None:
            text = str(value or "").strip()
            if text and text.casefold() not in {item.casefold() for item in candidates}:
                candidates.append(text)

        if ":" in entity_ref:
            prefix, _, suffix = entity_ref.partition(":")
            stripped_suffix = self._strip_structured_ref_type_prefix(
                value=suffix,
                entity_type=entity_type or prefix,
            )
            add(suffix)
            add(stripped_suffix)
        else:
            add(entity_ref)
        add(canonical_name)
        return candidates

    def _strip_structured_ref_type_prefix(self, *, value: str, entity_type: str) -> str:
        text = str(value or "").strip()
        normalized_type = str(entity_type or "").strip().casefold()
        if not text or not normalized_type:
            return text
        for separator in ("-", "_", ":"):
            marker = f"{normalized_type}{separator}"
            if text.casefold().startswith(marker):
                return text[len(marker) :].strip()
        return text

    def _inject_structured_entity_hints(
        self,
        event: MemoryEvent,
        existing_entities: list[dict[str, Any]],
    ) -> None:
        """Inject structured entity hints into existing_entities as Phase 1 context."""
        metadata_json = event.metadata_json
        if not isinstance(metadata_json, dict):
            return
        hints = metadata_json.get("structured_entity_hints")
        if not hints or not isinstance(hints, list):
            return

        host = self._structured_hint_host()
        existing_ids = {str(e.get("entity_id", "")) for e in existing_entities}
        injected_count = 0
        for hint in hints:
            if not isinstance(hint, dict):
                continue
            mention_text = str(hint.get("mention_text", "")).strip()
            entity_type = host._normalize_entity_type(hint.get("entity_type"))
            if not mention_text or not entity_type:
                continue

            canonical_name = str(hint.get("canonical_name_hint") or mention_text).strip()
            resolved_id = hint.get("resolved_entity_id")
            if resolved_id:
                entity_id = str(resolved_id)
            else:
                entity_id = host._build_canonical_entity_id(
                    entity_type=entity_type,
                    canonical_name=canonical_name,
                )

            if entity_id in existing_ids:
                continue

            existing_entities.append(
                {
                    "entity_id": entity_id,
                    "canonical_name": canonical_name,
                    "entity_type": entity_type,
                    "aliases": [canonical_name],
                    "hint_only": True,
                }
            )
            existing_ids.add(entity_id)
            injected_count += 1

        if injected_count:
            logger.debug(
                "L2 structured entity hints injected as context",
                event_id=event.event_id,
                hint_count=len(hints),
                injected_count=injected_count,
            )

    def _inject_structured_graph_hints(
        self,
        event: MemoryEvent,
        phase1_result: L2Phase1Result,
    ) -> None:
        """Inject structured graph hints as deterministic Phase 1 fact claims."""
        metadata_json = event.metadata_json
        if not isinstance(metadata_json, dict):
            return
        hints = metadata_json.get("structured_graph_hints")
        if not hints or not isinstance(hints, list):
            return

        host = self._structured_hint_host()
        existing_keys = {
            (
                host._non_empty_text(claim.subject_ref) or "",
                host._normalize_predicate(claim.predicate) or "",
                host._non_empty_text(claim.object_ref) or "",
                host._normalize_entity_type(claim.object_type) or "",
            )
            for claim in phase1_result.fact_claims
        }

        injected_count = 0
        for raw_hint in hints:
            if not isinstance(raw_hint, dict):
                continue
            hint = StructuredGraphHint.from_dict(raw_hint)
            subject_ref = host._non_empty_text(hint.subject_ref)
            predicate = host._normalize_predicate(hint.predicate)
            object_ref = host._non_empty_text(hint.object_ref)
            object_type = host._normalize_entity_type(hint.object_type)
            subject_type = host._non_empty_text(hint.subject_type) or "user"
            if not subject_ref or not predicate or not object_ref or not object_type:
                continue

            hint_key = (subject_ref, predicate, object_ref, object_type)
            if hint_key in existing_keys:
                continue

            phase1_result.fact_claims.append(
                L2Phase1FactClaim(
                    subject_ref=subject_ref,
                    subject_type=subject_type,
                    predicate=predicate,
                    object_ref=object_ref,
                    object_type=object_type,
                    fact_kind=host._non_empty_text(hint.fact_kind) or "explicit_fact",
                    polarity="positive",
                    specificity="concrete",
                    evidence_text=host._non_empty_text(hint.evidence_text) or "",
                    confidence=float(hint.confidence if hint.confidence is not None else 1.0),
                    supporting_event_ids=[event.event_id],
                )
            )
            existing_keys.add(hint_key)
            injected_count += 1

        if injected_count:
            logger.debug(
                "L2 structured graph hints injected as fact claims",
                event_id=event.event_id,
                hint_count=len(hints),
                injected_count=injected_count,
            )


__all__ = ["L2StructuredEntityHintMixin"]
