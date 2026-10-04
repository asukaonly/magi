"""Tests for personality.persona_journal_service module."""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from magi.personality.growth_memory import GrowthMemoryEngine, Milestone, MilestoneType
from magi.personality.persona_journal_service import (
    PersonaJournalService,
)


def _make_persona_config():
    """Create a mock PersonalityConfig for testing."""
    mock_config = MagicMock()
    mock_config.name = "小凯"
    mock_config.description = "productivity consultant"
    mock_config.identity_core.identity_statement = "A focused productivity consultant."
    return mock_config


def _patch_resolve(config=...):
    """Return a patch context manager for resolve_persona_config."""
    if config is ...:
        config = _make_persona_config()
    return patch(
        "magi.personality.persona_journal_service.resolve_persona_config",
        new_callable=AsyncMock,
        return_value=config,
    )


def _make_growth_engine():
    """Create a mock GrowthMemoryEngine."""
    engine = MagicMock(spec=GrowthMemoryEngine)

    def record_milestone_side_effect(milestone_type, title, description, metadata=None):
        return Milestone(
            id=f"milestone_{int(time.time() * 1000)}_0001",
            type=milestone_type,
            title=title,
            description=description,
            timestamp=time.time(),
            metadata=metadata or {},
        )

    engine.record_milestone = AsyncMock(side_effect=record_milestone_side_effect)
    engine.get_milestones = AsyncMock(return_value=[])
    return engine


class TestGenerateReflection:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("with_relationship", [False, True])
    @pytest.mark.parametrize("with_milestones", [False, True])
    async def test_reflection_context_reaches_selected_model_and_persisted_entry(
        self, with_relationship, with_milestones
    ):
        from magi.config.models import LLMScenario

        engine = _make_growth_engine()
        service = PersonaJournalService(growth_engine=engine)
        pool = MagicMock()
        bridge = MagicMock(chat=AsyncMock(return_value="  A thoughtful reflection.  "))
        emotions = {"mood": "content", "energy_level": 0.8, "stress_level": 0.1}
        with _patch_resolve(), patch(
            "magi.personality.persona_journal_service.get_scenario_llm_pool", return_value=pool
        ), patch(
            "magi.personality.persona_journal_service.LLMProviderBridge", return_value=bridge
        ) as factory:
            entry = await service.generate_reflection(
                persona_name="kai",
                emotional_state=emotions,
                relationship=(
                    {"trust_level": 0.8, "total_interactions": 50, "sentiment_score": 0.6}
                    if with_relationship
                    else None
                ),
                recent_milestones=(
                    [
                        {"title": f"Event {index}", "description": f"Detail {index}"}
                        for index in range(6)
                    ]
                    if with_milestones
                    else None
                ),
            )
        pool.get.assert_called_once_with(LLMScenario.AUXILIARY)
        factory.assert_called_once_with(pool.get.return_value)
        bridge.chat.assert_awaited_once()
        request = bridge.chat.await_args.kwargs
        assert len(request["messages"]) == 1
        assert request["messages"][0]["role"] == "user"
        prompt = request["messages"][0]["content"]
        assert "小凯" in prompt
        assert "A focused productivity consultant." in prompt
        assert "mood=content, energy=80%, stress=10%" in prompt
        assert ("trust=0.80, interactions=50, sentiment=0.60" in prompt) is with_relationship
        for index in range(5):
            assert (f"Event {index}: Detail {index}" in prompt) is with_milestones
        assert "Event 5" not in prompt
        assert "first person" in request["system_prompt"]
        assert request["max_tokens"] == 400
        assert request["disable_thinking"] is True
        assert request["event_context"] == {
            "request_kind": "personality:journal_reflection",
            "agent_id": "personality:journal",
        }
        assert entry is not None
        assert entry.content == "A thoughtful reflection."
        assert entry.metadata == {"persona_name": "kai", "emotional_snapshot": emotions}
        engine.record_milestone.assert_awaited_once_with(
            milestone_type=MilestoneType.JOURNAL_ENTRY,
            title="Persona reflection (kai)",
            description=entry.content,
            metadata=entry.metadata,
        )

    @pytest.mark.asyncio
    async def test_missing_persona_stops_before_model_or_storage(self):
        engine = _make_growth_engine()
        service = PersonaJournalService(growth_engine=engine)
        with _patch_resolve(config=None) as resolve, patch.object(
            service, "_call_llm", new=AsyncMock(return_value="Must not be generated")
        ) as model:
            entry = await service.generate_reflection(persona_name="nonexistent")
        assert entry is None
        resolve.assert_awaited_once_with("nonexistent")
        model.assert_not_awaited()
        engine.record_milestone.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_none_when_llm_fails(self):
        engine = _make_growth_engine()
        service = PersonaJournalService(growth_engine=engine)

        with _patch_resolve(), patch.object(service, "_call_llm", new=AsyncMock(return_value=None)):
            entry = await service.generate_reflection(persona_name="kai")

        assert entry is None
        engine.record_milestone.assert_not_awaited()


class TestGetRecentEntries:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "populated,persona,limit,expected",
        [
            (False, "kai", 5, []),
            (True, "kai", 5, ["m1", "m3", "m4", "m5"]),
            (True, "kai", 3, ["m1", "m3", "m4"]),
            (True, "alan", 5, ["m2"]),
            (True, "unknown", 5, []),
        ],
    )
    async def test_recent_entries_filter_before_limiting(self, populated, persona, limit, expected):
        engine = _make_growth_engine()
        engine.get_milestones.return_value = (
            [
                Milestone(
                    id=f"m{index}",
                    type=MilestoneType.JOURNAL_ENTRY,
                    title="Reflection",
                    description=f"Entry {index}",
                    timestamp=1700000000.0 - index * 3600,
                    metadata={"persona_name": "alan" if index == 2 else "kai"},
                )
                for index in range(1, 6)
            ]
            if populated
            else []
        )
        entries = await PersonaJournalService(growth_engine=engine).get_recent_entries(
            persona, limit=limit
        )
        assert [entry.milestone_id for entry in entries] == expected
        assert [entry.content for entry in entries] == ["Entry " + mid[1:] for mid in expected]
        assert all(entry.metadata["persona_name"] == persona for entry in entries)
        engine.get_milestones.assert_awaited_once_with(
            milestone_type=MilestoneType.JOURNAL_ENTRY, limit=limit * 3
        )


    @pytest.mark.asyncio
    async def test_handles_dict_milestones(self):
        """Test when growth engine returns dicts instead of Milestone objects."""
        engine = _make_growth_engine()
        engine.get_milestones = AsyncMock(return_value=[
            {
                "id": "m1",
                "type": "journal_entry",
                "title": "Persona reflection (kai)",
                "description": "Dict-format entry.",
                "timestamp": time.time(),
                "metadata": '{"persona_name": "kai"}',
            },
        ])

        service = PersonaJournalService(growth_engine=engine)
        entries = await service.get_recent_entries("kai")

        assert len(entries) == 1
        assert entries[0].content == "Dict-format entry."


class TestCallLlm:
    @pytest.mark.asyncio
    async def test_returns_none_when_pool_unavailable(self):
        engine = _make_growth_engine()
        service = PersonaJournalService(growth_engine=engine)

        with patch(
            "magi.personality.persona_journal_service.get_scenario_llm_pool",
            side_effect=RuntimeError("no pool"),
        ):
            result = await service._call_llm("test prompt")

        assert result is None
