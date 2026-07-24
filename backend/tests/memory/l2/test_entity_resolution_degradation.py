"""Tests for optional L2 entity-resolution degradation."""

from __future__ import annotations

import pytest

from magi.memory.l2.llm_json_client import L2InvalidJsonResponseError
from magi.memory.l2.models import L2Phase1Result


class _FailingLLMService:
    async def resolve_entities_batch(self, **_kwargs):  # type: ignore[no-untyped-def]
        raise L2InvalidJsonResponseError("invalid entity resolution JSON")


class _EntityCatalog:
    def __init__(self) -> None:
        self.recorded_mentions: list[dict[str, object]] = []
        self.upsert_count = 0

    async def resolve_alias(self, _alias_text, *, entity_type=None):  # type: ignore[no-untyped-def]
        return {"decision": "no_match"}

    async def find_resolution_candidates(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        return [
            {
                "entity_id": "organization:acme",
                "canonical_name": "Acme",
                "entity_type": "organization",
            }
        ]

    async def find_by_canonical_name(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        return []

    async def filter_projection_source_event_ids(
        self,
        *,
        event_ids,
        **_kwargs,
    ):  # type: ignore[no-untyped-def]
        return tuple(event_ids)

    async def record_mention(self, **kwargs):  # type: ignore[no-untyped-def]
        self.recorded_mentions.append(dict(kwargs))

    async def upsert_entity(self, **_kwargs):  # type: ignore[no-untyped-def]
        self.upsert_count += 1

    async def add_alias(self, **_kwargs):  # type: ignore[no-untyped-def]
        return None


@pytest.mark.asyncio
async def test_entity_resolution_json_failure_stays_unresolved() -> None:
    from memory.l2.test_pipeline import _make_memory_event
    from magi.memory.l2.pipeline import L2Pipeline

    catalog = _EntityCatalog()
    resolver = L2Pipeline.__new__(L2Pipeline)
    resolver._entity_catalog = catalog
    resolver._llm_service = _FailingLLMService()
    resolver._entity_resolution_cache = {}
    event = _make_memory_event(
        event_id="evt-acmex",
        content="我最近在关注 AcmeX",
    )
    phase1_result = L2Phase1Result.from_dict(
        {
            "entities": [
                {
                    "surface": "AcmeX",
                    "normalized_name": "AcmeX",
                    "entity_type": "organization",
                    "specificity": "concrete",
                    "confidence": 0.95,
                }
            ],
            "fact_claims": [],
            "resolved_refs": [],
        }
    )

    mentions = await resolver._resolve_phase1_entities(
        event,
        phase1_result,
        evidence_event_ids=[event.event_id],
        evidence_events=[event],
    )

    assert len(mentions) == 1
    assert mentions[0].resolved_entity_id is None
    assert mentions[0].evidence_event_ids == [event.event_id]
    assert catalog.upsert_count == 0
    assert phase1_result.diagnostics["degraded_stages"] == ["entity_resolution"]
