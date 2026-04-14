"""Tests for BootstrapDialogueService."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from magi.personality.bootstrap_service import BootstrapDialogueService
from magi.personality.growth_memory import GrowthMemoryEngine, Milestone, MilestoneType
from magi.personality.loader import BootstrapConfig, PersonalityConfig, PersonalityLoader


def _make_config(*, with_bootstrap: bool = True) -> PersonalityConfig:
    """Create a test personality config."""
    data = {
        "persona_entity": {
            "basic_profile": {
                "name": "TestBot",
                "core_background": "A test persona.",
            },
        },
        "cached_phrases": {"on_init": ["Hello."]},
        "bootstrap": {
            "style_instruction": "Be direct and friendly.",
            "opening_line": "Hey! What should I call you?",
            "extract_targets": ["name", "interests"],
            "max_rounds": 2,
        } if with_bootstrap else None,
    }
    if data["bootstrap"] is None:
        del data["bootstrap"]
    return PersonalityConfig.from_dict(data)


class TestBootstrapConfig:
    def test_from_dict_with_bootstrap(self):
        config = _make_config(with_bootstrap=True)
        assert config.bootstrap is not None
        assert config.bootstrap.style_instruction == "Be direct and friendly."
        assert config.bootstrap.opening_line == "Hey! What should I call you?"
        assert config.bootstrap.extract_targets == ["name", "interests"]
        assert config.bootstrap.max_rounds == 2

    def test_from_dict_without_bootstrap(self):
        config = _make_config(with_bootstrap=False)
        assert config.bootstrap is None

    def test_from_dict_defaults(self):
        config = PersonalityConfig.from_dict({"bootstrap": {}})
        assert config.bootstrap is not None
        assert config.bootstrap.max_rounds == 3
        assert config.bootstrap.style_instruction == ""
        assert config.bootstrap.extract_targets == []


class TestBootstrapNeedsCheck:
    @pytest.mark.asyncio
    async def test_needs_bootstrap_when_no_milestone(self):
        loader = MagicMock(spec=PersonalityLoader)
        loader.load.return_value = _make_config(with_bootstrap=False)

        growth = AsyncMock(spec=GrowthMemoryEngine)
        growth.get_milestones.return_value = []
        service = BootstrapDialogueService(
            personality_loader=loader,
            growth_engine=growth,
        )

        # All personas need bootstrap now (even without explicit config)
        assert await service.needs_bootstrap("test") is True

    @pytest.mark.asyncio
    async def test_needs_bootstrap_when_not_completed(self):
        loader = MagicMock(spec=PersonalityLoader)
        loader.load.return_value = _make_config(with_bootstrap=True)

        growth = AsyncMock(spec=GrowthMemoryEngine)
        growth.get_milestones.return_value = []

        service = BootstrapDialogueService(
            personality_loader=loader,
            growth_engine=growth,
        )

        assert await service.needs_bootstrap("test_persona") is True

    @pytest.mark.asyncio
    async def test_no_bootstrap_when_already_completed(self):
        loader = MagicMock(spec=PersonalityLoader)
        loader.load.return_value = _make_config(with_bootstrap=True)

        completed_milestone = Milestone(
            id="m1",
            type=MilestoneType.BOOTSTRAP_COMPLETED,
            title="bootstrap_completed_test_persona",
            description="done",
            timestamp=1000.0,
            metadata={"persona_name": "test_persona"},
        )
        growth = AsyncMock(spec=GrowthMemoryEngine)
        growth.get_milestones.return_value = [completed_milestone]

        service = BootstrapDialogueService(
            personality_loader=loader,
            growth_engine=growth,
        )

        assert await service.needs_bootstrap("test_persona") is False


class TestBootstrapOpening:
    @pytest.mark.asyncio
    async def test_get_opening_llm_success(self):
        loader = MagicMock(spec=PersonalityLoader)
        loader.load.return_value = _make_config(with_bootstrap=True)

        mock_bridge = AsyncMock()
        mock_bridge.chat.return_value = "Hey there, welcome!"
        mock_pool = MagicMock()
        mock_pool.get.return_value = mock_bridge

        service = BootstrapDialogueService(
            personality_loader=loader,
            growth_engine=AsyncMock(),
        )
        with patch("magi.personality.bootstrap_service.require_scenario_llm_pool", return_value=mock_pool):
            opening = await service.get_opening("test")
        assert opening == "Hey there, welcome!"

    @pytest.mark.asyncio
    async def test_get_opening_llm_fails_uses_static_fallback(self):
        loader = MagicMock(spec=PersonalityLoader)
        loader.load.return_value = _make_config(with_bootstrap=True)

        service = BootstrapDialogueService(
            personality_loader=loader,
            growth_engine=AsyncMock(),
        )
        # No LLM pool available → falls back to static opening_line
        opening = await service.get_opening("test")
        assert opening == "Hey! What should I call you?"

    @pytest.mark.asyncio
    async def test_get_opening_no_config_synthesizes_and_falls_back(self):
        loader = MagicMock(spec=PersonalityLoader)
        loader.load.return_value = _make_config(with_bootstrap=False)

        service = BootstrapDialogueService(
            personality_loader=loader,
            growth_engine=AsyncMock(),
        )
        # No bootstrap config → synthesized config has empty opening_line → returns None
        opening = await service.get_opening("test")
        assert opening is None


class TestBootstrapReply:
    @pytest.mark.asyncio
    async def test_reply_calls_llm(self):
        loader = MagicMock(spec=PersonalityLoader)
        loader.load.return_value = _make_config(with_bootstrap=True)

        growth = AsyncMock(spec=GrowthMemoryEngine)
        service = BootstrapDialogueService(
            personality_loader=loader,
            growth_engine=growth,
        )

        mock_bridge = AsyncMock()
        mock_bridge.chat.return_value = "Nice to meet you, Alice!"

        mock_pool = MagicMock()
        mock_pool.get.return_value = mock_bridge

        with patch("magi.personality.bootstrap_service.require_scenario_llm_pool", return_value=mock_pool):
            reply = await service.reply(
                persona_name="test",
                user_id="u1",
                session_id="s1",
                user_message="I'm Alice",
                history=[],
            )

        assert reply == "Nice to meet you, Alice!"
        mock_bridge.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_final_round_records_milestone(self):
        """On the final round, bootstrap should record a BOOTSTRAP_COMPLETED milestone."""
        loader = MagicMock(spec=PersonalityLoader)
        loader.load.return_value = _make_config(with_bootstrap=True)  # max_rounds=2

        growth = AsyncMock(spec=GrowthMemoryEngine)
        service = BootstrapDialogueService(
            personality_loader=loader,
            growth_engine=growth,
        )

        mock_bridge = AsyncMock()
        mock_bridge.chat.return_value = "Got it!"

        mock_pool = MagicMock()
        mock_pool.get.return_value = mock_bridge

        # Round 2 (final, because max_rounds=2): history has 1 user message already
        history = [
            {"role": "assistant", "content": "Hey!"},
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "What do you do?"},
        ]

        with patch("magi.personality.bootstrap_service.require_scenario_llm_pool", return_value=mock_pool):
            await service.reply(
                persona_name="my_persona",
                user_id="u1",
                session_id="s1",
                user_message="I'm a developer",
                history=history,
            )

        growth.record_milestone.assert_called_once()
        call_kwargs = growth.record_milestone.call_args[1]
        assert call_kwargs["milestone_type"] == MilestoneType.BOOTSTRAP_COMPLETED
        assert call_kwargs["metadata"]["persona_name"] == "my_persona"

    @pytest.mark.asyncio
    async def test_non_final_round_no_milestone(self):
        """Non-final round should not record milestone."""
        loader = MagicMock(spec=PersonalityLoader)
        loader.load.return_value = _make_config(with_bootstrap=True)  # max_rounds=2

        growth = AsyncMock(spec=GrowthMemoryEngine)
        service = BootstrapDialogueService(
            personality_loader=loader,
            growth_engine=growth,
        )

        mock_bridge = AsyncMock()
        mock_bridge.chat.return_value = "Tell me more!"
        mock_pool = MagicMock()
        mock_pool.get.return_value = mock_bridge

        with patch("magi.personality.bootstrap_service.require_scenario_llm_pool", return_value=mock_pool):
            await service.reply(
                persona_name="test",
                user_id="u1",
                session_id="s1",
                user_message="Hi",
                history=[],  # Round 1 of 2 — not final
            )

        growth.record_milestone.assert_not_called()


class TestBootstrapExtraction:
    @pytest.mark.asyncio
    async def test_extraction_writes_to_l2(self):
        loader = MagicMock(spec=PersonalityLoader)
        loader.load.return_value = _make_config(with_bootstrap=True)  # max_rounds=2

        growth = AsyncMock(spec=GrowthMemoryEngine)
        l2_store = AsyncMock()

        service = BootstrapDialogueService(
            personality_loader=loader,
            growth_engine=growth,
            l2_store=l2_store,
        )

        mock_bridge = AsyncMock()
        # First call: bootstrap reply, second call: extraction
        mock_bridge.chat.side_effect = [
            "Great meeting you!",
            json.dumps({"name": "Alice", "interests": ["coding", "music"]}),
        ]
        mock_pool = MagicMock()
        mock_pool.get.return_value = mock_bridge

        # Final round (round 2 of 2)
        history = [
            {"role": "assistant", "content": "Hey!"},
            {"role": "user", "content": "I'm Alice, I like coding"},
            {"role": "assistant", "content": "Cool!"},
        ]

        with patch("magi.personality.bootstrap_service.require_scenario_llm_pool", return_value=mock_pool):
            await service.reply(
                persona_name="test",
                user_id="u1",
                session_id="s1",
                user_message="And music",
                history=history,
            )

        # Should have called upsert_entity_facet for name and interests
        assert l2_store.upsert_entity_facet.call_count == 2
