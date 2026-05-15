"""Structured entity-hint injection for L2 extraction."""

from __future__ import annotations

from typing import Any

from .....core.logger import get_logger
from ....event_contracts import MemoryEvent
from ...models import L2Phase1FactClaim, L2Phase1Result, StructuredGraphHint
from .structured_hint_common import L2StructuredHintHostMixin

logger = get_logger(__name__)


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

        host = self._structured_hint_host()
        upserted_count = 0
        seen_ids: set[str] = set()

        async def upsert_hint(
            *,
            entity_id: str,
            entity_type: str,
            canonical_name: str,
            alias_text: str | None = None,
        ) -> None:
            nonlocal upserted_count
            if entity_id in seen_ids:
                return
            seen_ids.add(entity_id)
            await catalog.upsert_entity(
                entity_id=entity_id,
                canonical_name=canonical_name,
                entity_type=entity_type,
            )
            alias = host._non_empty_text(alias_text) or canonical_name
            if alias:
                await catalog.add_alias(entity_id=entity_id, alias_text=alias, confidence=0.98)
            upserted_count += 1

        raw_entity_hints = metadata_json.get("structured_entity_hints")
        if isinstance(raw_entity_hints, list):
            for hint in raw_entity_hints:
                if not isinstance(hint, dict):
                    continue
                mention_text = host._non_empty_text(hint.get("mention_text"))
                entity_type = host._normalize_entity_type(hint.get("entity_type"))
                if not mention_text or not entity_type:
                    continue
                canonical_name = (
                    host._non_empty_text(hint.get("canonical_name_hint")) or mention_text
                )
                resolved_id = host._non_empty_text(hint.get("resolved_entity_id"))
                entity_id = resolved_id or host._build_canonical_entity_id(
                    entity_type=entity_type,
                    canonical_name=canonical_name,
                )
                await upsert_hint(
                    entity_id=entity_id,
                    entity_type=entity_type,
                    canonical_name=canonical_name,
                    alias_text=mention_text,
                )

        raw_graph_hints = metadata_json.get("structured_graph_hints")
        if isinstance(raw_graph_hints, list):
            for hint in raw_graph_hints:
                if not isinstance(hint, dict):
                    continue
                for ref_key, type_key in (
                    ("subject_ref", "subject_type"),
                    ("object_ref", "object_type"),
                ):
                    entity_ref = host._non_empty_text(hint.get(ref_key))
                    entity_type = host._normalize_entity_type(hint.get(type_key))
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
                    await upsert_hint(
                        entity_id=entity_ref,
                        entity_type=entity_type,
                        canonical_name=canonical_name,
                    )

        if upserted_count:
            logger.debug(
                "L2 structured entity hints persisted",
                event_id=event.event_id,
                upserted_count=upserted_count,
            )
        return upserted_count

    def _canonical_name_from_entity_ref(self, *, entity_ref: str, entity_type: str) -> str:
        _, _, suffix = entity_ref.partition(":")
        text = suffix or entity_ref
        normalized_type = str(entity_type or "").strip().casefold()
        for separator in ("-", "_", ":"):
            marker = f"{normalized_type}{separator}"
            if text.casefold().startswith(marker):
                text = text[len(marker):]
                break
        return text.replace("_", " ").replace("-", " ").strip() or entity_ref

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
