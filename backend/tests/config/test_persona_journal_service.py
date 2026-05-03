"""Tests for personality.persona_journal_service module."""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from magi.personality.growth_memory import GrowthMemoryEngine, Milestone, MilestoneType
from magi.personality.persona_journal_service import (
    JournalEntry,
    PersonaJournalService,
)


def _make_persona_config():
    """Create a mock PersonalityConfig for testing."""
    mock_config = MagicMock()
    mock_config.name = "小凯"
    mock_config.description = "productivity consultant"
    mock_config.identity_core.identity_statement = "A focused productivity consultant."
    return mock_config


def _patch_resolve(config=None):
    """Return a patch context manager for resolve_persona_config."""
    if config is None:
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
    async def test_generates_and_stores_reflection(self):
        engine = _make_growth_engine()
        service = PersonaJournalService(growth_engine=engine)

        with _patch_resolve(), patch.object(service, "_call_llm", new=AsyncMock(return_value="Today I reflected on a productive chat.")):
            entry = await service.generate_reflection(
                persona_name="kai",
                emotional_state={"mood": "content", "energy_level": 0.8, "stress_level": 0.1},
            )

        assert entry is not None
        assert entry.content == "Today I reflected on a productive chat."
        assert entry.metadata["persona_name"] == "kai"
        assert entry.metadata["emotional_snapshot"]["mood"] == "content"

        engine.record_milestone.assert_awaited_once()
        call_kwargs = engine.record_milestone.call_args[1]
        assert call_kwargs["milestone_type"] == MilestoneType.JOURNAL_ENTRY
        assert "kai" in call_kwargs["title"]

    @pytest.mark.asyncio
    async def test_returns_none_when_persona_not_found(self):
        engine = _make_growth_engine()
        service = PersonaJournalService(growth_engine=engine)

        with _patch_resolve(config=None):
            entry = await service.generate_reflection(persona_name="nonexistent")
        assert entry is None

    @pytest.mark.asyncio
    async def test_returns_none_when_llm_fails(self):
        engine = _make_growth_engine()
        service = PersonaJournalService(growth_engine=engine)

        with _patch_resolve(), patch.object(service, "_call_llm", new=AsyncMock(return_value=None)):
            entry = await service.generate_reflection(persona_name="kai")

        assert entry is None
        engine.record_milestone.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_includes_relationship_in_prompt(self):
        engine = _make_growth_engine()
        service = PersonaJournalService(growth_engine=engine)

        captured_prompt = None

        async def capture_llm(prompt):
            nonlocal captured_prompt
            captured_prompt = prompt
            return "A reflection entry."

        with _patch_resolve(), patch.object(service, "_call_llm", new=capture_llm):
            await service.generate_reflection(
                persona_name="kai",
                relationship={"trust_level": 0.8, "total_interactions": 50, "sentiment_score": 0.6},
            )

        assert captured_prompt is not None
        assert "trust=0.80" in captured_prompt
        assert "interactions=50" in captured_prompt

    @pytest.mark.asyncio
    async def test_includes_milestones_in_prompt(self):
        engine = _make_growth_engine()
        service = PersonaJournalService(growth_engine=engine)

        captured_prompt = None

        async def capture_llm(prompt):
            nonlocal captured_prompt
            captured_prompt = prompt
            return "A reflection."

        milestones = [
            {"title": "First chat", "description": "Had first conversation"},
            {"title": "Deep discussion", "description": "Discussed philosophy"},
        ]

        with _patch_resolve(), patch.object(service, "_call_llm", new=capture_llm):
            await service.generate_reflection(
                persona_name="kai",
                recent_milestones=milestones,
            )

        assert captured_prompt is not None
        assert "First chat" in captured_prompt
        assert "Deep discussion" in captured_prompt


class TestGetRecentEntries:
    @pytest.mark.asyncio
    async def test_returns_matching_entries(self):
        engine = _make_growth_engine()
        engine.get_milestones = AsyncMock(return_value=[
            Milestone(
                id="m1",
                type=MilestoneType.JOURNAL_ENTRY,
                title="Persona reflection (kai)",
                description="I felt productive today.",
                timestamp=time.time() - 3600,
                metadata={"persona_name": "kai"},
            ),
            Milestone(
                id="m2",
                type=MilestoneType.JOURNAL_ENTRY,
                title="Persona reflection (alan)",
                description="Curious about user patterns.",
                timestamp=time.time() - 7200,
                metadata={"persona_name": "alan"},
            ),
            Milestone(
                id="m3",
                type=MilestoneType.JOURNAL_ENTRY,
                title="Persona reflection (kai)",
                description="Good interactions overall.",
                timestamp=time.time() - 86400,
                metadata={"persona_name": "kai"},
            ),
        ])

        service = PersonaJournalService(growth_engine=engine)
        entries = await service.get_recent_entries("kai", limit=5)

        assert len(entries) == 2
        assert entries[0].milestone_id == "m1"
        assert entries[1].milestone_id == "m3"
        assert all(e.metadata["persona_name"] == "kai" for e in entries)

    @pytest.mark.asyncio
    async def test_respects_limit(self):
        engine = _make_growth_engine()
        engine.get_milestones = AsyncMock(return_value=[
            Milestone(
                id=f"m{i}",
                type=MilestoneType.JOURNAL_ENTRY,
                title="Persona reflection (kai)",
                description=f"Entry {i}",
                timestamp=time.time() - i * 3600,
                metadata={"persona_name": "kai"},
            )
            for i in range(10)
        ])

        service = PersonaJournalService(growth_engine=engine)
        entries = await service.get_recent_entries("kai", limit=3)

        assert len(entries) == 3

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_entries(self):
        engine = _make_growth_engine()
        engine.get_milestones = AsyncMock(return_value=[])

        service = PersonaJournalService(growth_engine=engine)
        entries = await service.get_recent_entries("kai")

        assert entries == []

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

    @pytest.mark.asyncio
    async def test_successful_llm_call(self):
        engine = _make_growth_engine()
        service = PersonaJournalService(growth_engine=engine)

        mock_bridge = MagicMock()
        mock_bridge.chat = AsyncMock(return_value="A thoughtful reflection.")
        mock_pool = MagicMock()
        mock_pool.get.return_value = MagicMock()

        with (
            patch(
                "magi.personality.persona_journal_service.get_scenario_llm_pool",
                return_value=mock_pool,
            ),
            patch(
                "magi.personality.persona_journal_service.LLMProviderBridge",
                return_value=mock_bridge,
            ),
        ):
            result = await service._call_llm("test prompt")

        assert result == "A thoughtful reflection."
