from __future__ import annotations

from magi.timeline.context_bundle_builder import TimelineContextBundleBuilder


class _FakeL1Store:
    async def get_user_visible_event(self, event_id: str):  # type: ignore[no-untyped-def]
        if event_id == "evt-1":
            return {
                "event_id": "evt-1",
                "idempotency_key": "chat_msg:turn-1:user",
                "timestamp": 100.0,
                "source": "chat",
                "content": "Discussed the timeline redesign.",
                "metadata": {
                    "activity_snapshot": {
                        "title": "Chat planning",
                        "summary": "Discussed semantic zoom.",
                    }
                },
            }
        return None


class _FakeL2Store:
    async def list_tom_assertions(self, **kwargs):  # type: ignore[no-untyped-def]
        return [
            {
                "assertion_id": "assertion-1",
                "entity_id": "user:u1",
                "trait_name": "mood",
                "trait_value": "focused",
                "confidence_score": 0.8,
                "evidence_events": ["evt-1"],
            },
            {
                "assertion_id": "assertion-2",
                "entity_id": "user:other",
                "trait_name": "mood",
                "trait_value": "distracted",
                "confidence_score": 0.2,
                "evidence_events": ["evt-9"],
            },
        ]

    async def find_edges_by_event_id(self, event_id: str):  # type: ignore[no-untyped-def]
        if event_id != "evt-1":
            return []
        return [
            {
                "triple_id": "edge-1",
                "subject_id": "user:u1",
                "predicate": "LIKES",
                "object_id": "person:asuka",
                "evidence_event_ids": ["evt-1"],
            }
        ]


class _FakeL3Store:
    async def list_summaries(self, *, limit: int = 100):  # type: ignore[no-untyped-def]
        return [
            {
                "summary_id": "summary-1",
                "summary_category": "day",
                "content": "Focus remained high.",
                "source_event_ids": ["evt-1"],
            }
        ]


class _FakeL4Store:
    async def get_all_skills(self, *, limit: int = 100):  # type: ignore[no-untyped-def]
        return [
            {
                "skill_id": "skill-1",
                "skill_name": "Deep work loop",
                "success_rate": 0.81,
            }
        ]


async def test_context_bundle_builder_collects_cross_layer_evidence() -> None:
    builder = TimelineContextBundleBuilder(
        l1_store=_FakeL1Store(),
        l2_store=_FakeL2Store(),
        l3_store=_FakeL3Store(),
        l4_store=_FakeL4Store(),
    )

    bundle = await builder.build(
        anchor={
            "anchor_id": "cluster:0",
            "anchor_type": "cluster",
            "title": "Deep work",
            "summary": "A focused planning stretch.",
            "representative_event_ids": ["evt-1"],
        }
    )

    assert bundle["anchor"]["anchor_id"] == "cluster:0"
    assert bundle["l1_events"][0]["event_id"] == "evt-1"
    assert bundle["l1_events"][0]["source_item_id"] == "chat_msg:turn-1:user"
    assert bundle["l2_state_evidence"][0]["assertion_id"] == "assertion-1"
    assert bundle["l2_state_evidence"][1]["triple_id"] == "edge-1"
    assert bundle["l3_reflections"][0]["summary_id"] == "summary-1"
    assert bundle["l4_related_procedures"][0]["skill_id"] == "skill-1"
