"""Tests for personality bootstrap and journal API endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from magi.api.routers.personality_config import (
    BootstrapMessageRequest,
    JournalReflectRequest,
    api_bootstrap_message,
    api_get_greeting,
    api_journal_reflect,
)


@pytest.fixture(autouse=True)
def _reset_growth_engine():
    """Reset the cached growth engine between tests."""
    import magi.api.routers.personality_config as mod
    original = mod._growth_engine_instance
    mod._growth_engine_instance = None
    yield
    mod._growth_engine_instance = original


def _mock_config(*, with_bootstrap: bool = True):
    config = MagicMock()
    config.name = "TestBot"
    config.avatar = ""
    config.cached_phrases.on_init = ["Hello."]
    config.persona_entity.basic_profile.name = "TestBot"
    config.persona_entity.basic_profile.core_background = "A test persona."
    config.persona_entity.psychological_traits.communication_tone = "Neutral"
    if with_bootstrap:
        config.bootstrap = MagicMock()
        config.bootstrap.opening_line = "Hey, first time here."
        config.bootstrap.style_instruction = "Speak naturally."
        config.bootstrap.extract_targets = ["name"]
        config.bootstrap.max_rounds = 3
    else:
        config.bootstrap = None
    return config


class TestGreetingBootstrapStatus:
    """Greeting endpoint includes bootstrap status."""

    @pytest.mark.asyncio
    async def test_greeting_includes_needs_bootstrap_true(self):
        mock_engine = AsyncMock()
        mock_engine.init = AsyncMock()
        mock_engine.get_milestones = AsyncMock(return_value=[])

        config = _mock_config(with_bootstrap=True)

        with (
            patch("magi.api.routers.personality_config.get_current_personality_name", return_value="testbot"),
            patch("magi.api.routers.personality_config.get_personality_loader") as mock_loader_fn,
            patch("magi.api.routers.personality_config.GrowthMemoryEngine", return_value=mock_engine),
            patch("magi.api.routers.personality_config.resolve_avatar_public_url", return_value=""),
            patch("magi.api.routers.personality_config.get_runtime_paths") as mock_paths,
        ):
            mock_paths.return_value.personalities_dir = "/tmp/test"
            mock_paths.return_value.growth_db_path = "/tmp/test/growth.db"
            mock_loader_fn.return_value.load.return_value = config

            resp = await api_get_greeting()

        assert resp.data["needs_bootstrap"] is True
        assert resp.data["bootstrap_opening"] == "Hey, first time here."

    @pytest.mark.asyncio
    async def test_greeting_bootstrap_false_when_completed(self):
        milestone = MagicMock()
        milestone.metadata = {"persona_name": "testbot"}
        mock_engine = AsyncMock()
        mock_engine.init = AsyncMock()
        mock_engine.get_milestones = AsyncMock(return_value=[milestone])

        config = _mock_config(with_bootstrap=True)

        with (
            patch("magi.api.routers.personality_config.get_current_personality_name", return_value="testbot"),
            patch("magi.api.routers.personality_config.get_personality_loader") as mock_loader_fn,
            patch("magi.api.routers.personality_config.GrowthMemoryEngine", return_value=mock_engine),
            patch("magi.api.routers.personality_config.resolve_avatar_public_url", return_value=""),
            patch("magi.api.routers.personality_config.get_runtime_paths") as mock_paths,
        ):
            mock_paths.return_value.personalities_dir = "/tmp/test"
            mock_paths.return_value.growth_db_path = "/tmp/test/growth.db"
            mock_loader_fn.return_value.load.return_value = config

            resp = await api_get_greeting()

        assert resp.data["needs_bootstrap"] is False
        assert resp.data["bootstrap_opening"] is None

    @pytest.mark.asyncio
    async def test_greeting_bootstrap_graceful_on_error(self):
        """Bootstrap check failure should not break the greeting."""
        config = _mock_config(with_bootstrap=False)

        with (
            patch("magi.api.routers.personality_config.get_current_personality_name", return_value="testbot"),
            patch("magi.api.routers.personality_config.get_personality_loader") as mock_loader_fn,
            patch("magi.api.routers.personality_config.GrowthMemoryEngine", side_effect=RuntimeError("DB error")),
            patch("magi.api.routers.personality_config.resolve_avatar_public_url", return_value=""),
            patch("magi.api.routers.personality_config.get_runtime_paths") as mock_paths,
        ):
            mock_paths.return_value.personalities_dir = "/tmp/test"
            mock_paths.return_value.growth_db_path = "/tmp/test/growth.db"
            mock_loader_fn.return_value.load.return_value = config

            resp = await api_get_greeting()

        assert resp.success is True
        assert resp.data["needs_bootstrap"] is False


class TestBootstrapMessageEndpoint:
    """POST /bootstrap/message endpoint tests."""

    @pytest.mark.asyncio
    async def test_returns_reply(self):
        mock_engine = AsyncMock()
        mock_engine.init = AsyncMock()
        mock_engine.get_milestones = AsyncMock(return_value=[])
        mock_engine.record_milestone = AsyncMock(return_value=MagicMock(id="m1", timestamp=1.0))

        config = _mock_config(with_bootstrap=True)
        config.bootstrap.max_rounds = 2
        config.bootstrap.style_instruction = "Be friendly."
        config.bootstrap.extract_targets = ["name"]

        with (
            patch("magi.api.routers.personality_config.get_current_personality_name", return_value="testbot"),
            patch("magi.api.routers.personality_config.GrowthMemoryEngine", return_value=mock_engine),
            patch("magi.api.routers.personality_config.get_runtime_paths") as mock_paths,
            patch("magi.api.routers.personality_config.get_personality_loader") as mock_loader_fn,
            patch("magi.personality.bootstrap_service.require_scenario_llm_pool") as mock_pool,
        ):
            mock_paths.return_value.personalities_dir = "/tmp/test"
            mock_paths.return_value.growth_db_path = "/tmp/test/growth.db"
            mock_loader_fn.return_value.load.return_value = config
            mock_pool.return_value.get.return_value.chat = AsyncMock(return_value="Nice to meet you!")

            request = BootstrapMessageRequest(
                user_message="I'm Alice",
                history=[],
            )
            resp = await api_bootstrap_message(request)

        assert resp.success is True
        assert resp.data["reply"] == "Nice to meet you!"

    @pytest.mark.asyncio
    async def test_already_completed(self):
        milestone = MagicMock()
        milestone.metadata = {"persona_name": "testbot"}
        mock_engine = AsyncMock()
        mock_engine.init = AsyncMock()
        mock_engine.get_milestones = AsyncMock(return_value=[milestone])

        config = _mock_config(with_bootstrap=True)

        with (
            patch("magi.api.routers.personality_config.get_current_personality_name", return_value="testbot"),
            patch("magi.api.routers.personality_config.GrowthMemoryEngine", return_value=mock_engine),
            patch("magi.api.routers.personality_config.get_runtime_paths") as mock_paths,
            patch("magi.api.routers.personality_config.get_personality_loader") as mock_loader_fn,
        ):
            mock_paths.return_value.personalities_dir = "/tmp/test"
            mock_paths.return_value.growth_db_path = "/tmp/test/growth.db"
            mock_loader_fn.return_value.load.return_value = config

            request = BootstrapMessageRequest(user_message="Hi")
            resp = await api_bootstrap_message(request)

        assert resp.data["is_complete"] is True
        assert resp.data["reply"] is None


class TestJournalReflectEndpoint:
    """POST /journal/reflect endpoint tests."""

    @pytest.mark.asyncio
    async def test_successful_reflection(self):
        mock_engine = AsyncMock()
        mock_engine.init = AsyncMock()
        mock_engine.record_milestone = AsyncMock(
            return_value=MagicMock(id="j1", description="I felt calm today.", timestamp=100.0)
        )

        config = _mock_config(with_bootstrap=False)
        config.persona_entity.basic_profile.name = "TestBot"
        config.persona_entity.basic_profile.occupation = "Tester"

        with (
            patch("magi.api.routers.personality_config.get_current_personality_name", return_value="testbot"),
            patch("magi.api.routers.personality_config.GrowthMemoryEngine", return_value=mock_engine),
            patch("magi.api.routers.personality_config.get_runtime_paths") as mock_paths,
            patch("magi.api.routers.personality_config.get_personality_loader") as mock_loader_fn,
            patch("magi.personality.persona_journal_service.PersonaJournalService._call_llm",
                  new_callable=AsyncMock, return_value="I felt calm today."),
        ):
            mock_paths.return_value.personalities_dir = "/tmp/test"
            mock_paths.return_value.growth_db_path = "/tmp/test/growth.db"
            mock_loader_fn.return_value.load.return_value = config

            request = JournalReflectRequest()
            resp = await api_journal_reflect(request)

        assert resp.success is True
        assert resp.data["content"] == "I felt calm today."
        assert resp.data["milestone_id"] == "j1"

    @pytest.mark.asyncio
    async def test_reflection_failure_returns_false(self):
        mock_engine = AsyncMock()
        mock_engine.init = AsyncMock()

        with (
            patch("magi.api.routers.personality_config.get_current_personality_name", return_value="testbot"),
            patch("magi.api.routers.personality_config.GrowthMemoryEngine", return_value=mock_engine),
            patch("magi.api.routers.personality_config.get_runtime_paths") as mock_paths,
            patch("magi.api.routers.personality_config.get_personality_loader") as mock_loader_fn,
            patch("magi.personality.persona_journal_service.PersonaJournalService._call_llm",
                  new_callable=AsyncMock, return_value=None),
        ):
            mock_paths.return_value.personalities_dir = "/tmp/test"
            mock_paths.return_value.growth_db_path = "/tmp/test/growth.db"
            mock_loader_fn.return_value.load.return_value = None

            request = JournalReflectRequest()
            resp = await api_journal_reflect(request)

        assert resp.success is False
