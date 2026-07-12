"""Entity resolution prompt execution for L2."""

from __future__ import annotations

from .models import (
    L2BatchEntityResolutionItem,
    L2EntityCandidate,
    L2EntityResolution,
    L2EntityResolutionMention,
)
from .llm_priority import l2_llm_priority_for_source
from .pipeline.prompts import (
    BATCH_ENTITY_RESOLUTION_SYSTEM_PROMPT,
    ENTITY_RESOLUTION_SYSTEM_PROMPT,
    render_batch_entity_resolution_prompt,
    render_entity_resolution_prompt,
)


class L2LLMEntityResolutionMixin:
    """Execute single and batch entity resolution prompts."""

    async def resolve_entity(
        self,
        *,
        mention: L2EntityResolutionMention,
        candidate_entities: list[L2EntityCandidate],
        min_confidence: float = 0.8,
        source: str | None = None,
    ) -> L2EntityResolution:
        payload = await self._generate_json(
            system_prompt=ENTITY_RESOLUTION_SYSTEM_PROMPT,
            prompt=render_entity_resolution_prompt(
                mention=mention, candidate_entities=candidate_entities
            ),
            request_kind="memory:l2_entity_resolution",
            priority=l2_llm_priority_for_source(source),
            required_fields={"resolution": dict},
        )
        resolution = payload.get("resolution")
        if not isinstance(resolution, dict):
            return self._unresolved_resolution()

        confidence = float(resolution.get("confidence", 0.0) or 0.0)
        decision = str(resolution.get("decision", "unresolved"))
        if decision == "match" and confidence < min_confidence:
            return self._unresolved_resolution(confidence=confidence)

        matched_entity_id = resolution.get("matched_entity_id")
        if decision != "match" or not matched_entity_id:
            return self._unresolved_resolution(confidence=confidence)

        return L2EntityResolution(
            decision="match",
            matched_entity_id=str(matched_entity_id),
            matched_entity_name=resolution.get("matched_entity_name"),
            confidence=confidence,
            reason_tags=resolution.get("reason_tags", []),
            should_merge=bool(resolution.get("should_merge", False)),
            canonical_name_suggestion=resolution.get("canonical_name_suggestion"),
        )

    async def resolve_entities_batch(
        self,
        *,
        items: list[L2BatchEntityResolutionItem],
        min_confidence: float = 0.8,
        source: str | None = None,
    ) -> dict[str, L2EntityResolution]:
        """Resolve multiple entity mentions in a single LLM call."""
        if not items:
            return {}

        if len(items) == 1:
            item = items[0]
            result = await self.resolve_entity(
                mention=item.mention,
                candidate_entities=item.candidate_entities,
                min_confidence=min_confidence,
                source=source,
            )
            return {item.mention_key: result}

        payload = await self._generate_json(
            system_prompt=BATCH_ENTITY_RESOLUTION_SYSTEM_PROMPT,
            prompt=render_batch_entity_resolution_prompt(items=items),
            request_kind="memory:l2_entity_resolution",
            priority=l2_llm_priority_for_source(source),
            required_fields={"resolutions": list},
        )
        raw_resolutions = payload.get("resolutions")
        if not isinstance(raw_resolutions, list):
            return {item.mention_key: self._unresolved_resolution() for item in items}

        results: dict[str, L2EntityResolution] = {}
        for raw in raw_resolutions:
            if not isinstance(raw, dict):
                continue
            mention_key = str(raw.get("mention_key", ""))
            if not mention_key:
                continue
            confidence = float(raw.get("confidence", 0.0) or 0.0)
            decision = str(raw.get("decision", "unresolved"))
            if decision == "match" and confidence < min_confidence:
                results[mention_key] = self._unresolved_resolution(confidence=confidence)
                continue
            matched_entity_id = raw.get("matched_entity_id")
            if decision != "match" or not matched_entity_id:
                results[mention_key] = self._unresolved_resolution(confidence=confidence)
                continue
            results[mention_key] = L2EntityResolution(
                decision="match",
                matched_entity_id=str(matched_entity_id),
                matched_entity_name=raw.get("matched_entity_name"),
                confidence=confidence,
                reason_tags=raw.get("reason_tags", []),
                should_merge=bool(raw.get("should_merge", False)),
                canonical_name_suggestion=raw.get("canonical_name_suggestion"),
            )

        for item in items:
            if item.mention_key not in results:
                results[item.mention_key] = self._unresolved_resolution()

        return results


__all__ = ["L2LLMEntityResolutionMixin"]
