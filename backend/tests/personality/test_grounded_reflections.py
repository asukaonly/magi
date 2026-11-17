"""Exercise persistence, evidence invalidation and silent context consumption."""

import json
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from magi.config.models import PersonalitySettings
from magi.personality.persona_journal_service import PersonaJournalService
from magi.personality.reflection_store import ReflectionStore


@asynccontextmanager
async def guard():
    yield


@pytest.fixture
def harness(tmp_path, ensure_db_schema, monkeypatch):
    path = tmp_path / "growth.db"
    ensure_db_schema("growth_memory", path)
    settings = PersonalitySettings(enable_background_reflection=True)
    monkeypatch.setattr("magi.personality.persona_journal_service.get_config", lambda: SimpleNamespace(agent=SimpleNamespace(personality=settings)))
    persona = SimpleNamespace(persona_id="p1", updated_at=1, name="Magi", config=SimpleNamespace(
        description="Quiet and curious", identity_core=SimpleNamespace(identity_statement="Consider evidence"), idiolect=None,
    ))
    events = [{"event_id": "e1", "user_id": "u1", "source": "chat", "author_type": "user",
               "content": "Please consider maintenance costs.", "timestamp": time.time()-1800},
              {"event_id": "e2", "user_id": "u1", "source": "chat", "author_type": "assistant",
               "content": "I focused only on speed.", "timestamp": time.time()-1800}]
    evidence = SimpleNamespace(
        memory=SimpleNamespace(memory_operation_guard=guard, memory_operation_epoch=lambda: 1),
        governance_revision=AsyncMock(return_value="r1"), recent=AsyncMock(return_value=events),
        last_chat_at=AsyncMock(return_value=0),
        current=AsyncMock(side_effect=lambda _user, ids: [e for e in events if e["event_id"] in ids]),
    )
    draft = {"kind": "self_review", "topic": "Maintenance costs", "content": "I should consider maintenance alongside speed.",
             "applicability": "When evaluating engineering tradeoffs", "citations": [
                 {"event_id": "e1", "quote": "maintenance costs"}, {"event_id": "e2", "quote": "only on speed"}]}
    generate = AsyncMock(return_value=json.dumps({"thoughts": [draft]}))
    store = ReflectionStore(str(path))
    service = PersonaJournalService(store=store, evidence=evidence,
                                   personas=SimpleNamespace(get=AsyncMock(return_value=persona), get_by_slug=AsyncMock(return_value=persona), get_active_id=AsyncMock(return_value="p1")),
                                   allow_event=AsyncMock(return_value=True), generate=generate,
                                   verify=AsyncMock(return_value='{"supported": [true]}'))
    return SimpleNamespace(service=service, store=store, evidence=evidence, settings=settings, events=events,
                           generate=generate, draft=draft, persona=persona)


async def test_reflection_is_grounded_idempotent_and_only_used_when_relevant(harness):
    h = harness
    assert await h.service.reflect("u1", "p1") == "completed"
    assert await h.service.reflect("u1", "p1") == "unchanged_or_budget"
    h.generate.assert_awaited_once()
    page = await h.service.page("u1", "p1")
    assert len(page.items) == 1
    assert len((await h.service.detail("u1", "p1", page.items[0].id)).evidence) == 2
    assert await h.service.relevant(user_id="u1", persona_name="magi", query="maintenance costs")
    assert await h.service.relevant(user_id="u1", persona_name="magi", query="weather") == []
    assert await h.store.rows("other-user", "p1") == []
    assert await h.store.rows("u1", "other-persona") == []


@pytest.mark.parametrize("change", ["source_deleted", "source_changed", "correction", "persona_changed"])
async def test_changed_evidence_cannot_reach_later_context(harness, change):
    h = harness
    await h.service.reflect("u1", "p1")
    if change == "source_deleted":
        h.events.pop()
    elif change == "source_changed":
        h.events[0]["content"] = "The old statement is wrong."
    elif change == "correction":
        h.evidence.governance_revision.return_value = "r2"
    else:
        h.persona.updated_at = 2
    assert (await h.service.page("u1", "p1")).items == []
    assert await h.service.relevant(user_id="u1", persona_name="magi", query="maintenance") == []


async def test_dismissed_topic_cannot_be_recreated_by_new_run(harness):
    h = harness
    await h.service.reflect("u1", "p1")
    thought = (await h.service.page("u1", "p1")).items[0]
    await h.service.dismiss("u1", "p1", thought.id)
    await h.service.dismiss("u1", "p1", thought.id)
    h.events[0]["content"] += " More context."
    assert await h.service.reflect("u1", "p1") == "completed"
    assert (await h.service.page("u1", "p1")).items == []


@pytest.mark.parametrize("change", ["disabled", "clear", "delete", "persona"])
async def test_generation_rechecks_admission_before_write(harness, change):
    h = harness
    async def generate(_prompt):
        if change == "disabled":
            h.settings.enable_background_reflection = False
        elif change == "clear":
            h.evidence.memory.memory_operation_epoch = lambda: 2
        elif change == "delete":
            h.events.pop()
        else:
            h.persona.updated_at = 2
        return json.dumps({"thoughts": [h.draft]})
    h.service._generate = generate
    assert await h.service.reflect("u1", "p1") == "stale"
    assert (await h.service.page("u1", "p1")).items == []


async def test_unquoted_claim_rejected_and_disabled_feature_makes_no_call(harness):
    h = harness
    h.settings.enable_background_reflection = False
    assert await h.service.reflect("u1", "p1") == "disabled"
    h.generate.assert_not_awaited()
    h.settings.enable_background_reflection = True
    h.draft["citations"][0]["quote"] = "invented source text"
    h.generate.return_value = json.dumps({"thoughts": [h.draft]})
    with pytest.raises(ValueError, match="citation"):
        await h.service.reflect("u1", "p1")
    assert (await h.service.page("u1", "p1")).items == []


async def test_budget_is_shared_across_personas(harness):
    h = harness
    assert await h.store.reserve("u1", "p1", "one", daily_limit=2)
    assert await h.store.reserve("u1", "p2", "two", daily_limit=2)
    assert not await h.store.reserve("u1", "p3", "three", daily_limit=2)


async def test_semantic_rejection_and_empty_batch_are_valid_noops(harness):
    h = harness
    h.service._verify.return_value = '{"supported": [false]}'
    assert await h.service.reflect("u1", "p1") == "completed"
    assert (await h.service.page("u1", "p1")).items == []


async def test_sharing_requires_opt_in_and_is_at_most_once_per_day(harness):
    h = harness
    await h.service.reflect("u1", "p1")
    assert (await h.service.share("u1")).thought is None
    h.settings.enable_proactive_sharing = True
    assert (await h.service.share("u1")).thought is not None
    assert (await h.service.share("u1")).thought is None


async def test_forgetting_source_scrubs_even_dismissed_thoughts(harness):
    h = harness
    await h.service.reflect("u1", "p1")
    thought = (await h.service.page("u1", "p1")).items[0]
    await h.service.dismiss("u1", "p1", thought.id)
    await h.store.forget_events(["e1"])
    assert await h.store.rows("u1", "p1") == []
