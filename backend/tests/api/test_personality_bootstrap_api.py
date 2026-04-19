"""Tests for personality bootstrap and journal API endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from magi.api.routers.personality_config import (
    BootstrapInitRequest,
    BootstrapMessageRequest,
    JournalReflectRequest,
    api_bootstrap_init,
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
    config.persona_entity.basic_profile.name = "TestBot"
    config.persona_entity.core_identity.inner_narrative = "A test persona."
    config.persona_entity.core_identity.language_fingerprint = "Neutral"
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
            patch("magi.api.routers.personality_config.get_current_personality_config", return_value=config),
            patch("magi.api.routers.personality_config.GrowthMemoryEngine", return_value=mock_engine),
            patch("magi.api.routers.personality_config.resolve_avatar_public_url", return_value=""),
            patch("magi.api.routers.personality_config.get_runtime_paths") as mock_paths,
            patch("magi.personality.bootstrap_service.resolve_persona_config", new_callable=AsyncMock, return_value=config),
        ):
            mock_paths.return_value.growth_db_path = "/tmp/test/growth.db"
            mock_paths.return_value.persona_registry_db_path = "/tmp/test/persona_registry.db"

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
            patch("magi.api.routers.personality_config.get_current_personality_config", return_value=config),
            patch("magi.api.routers.personality_config.GrowthMemoryEngine", return_value=mock_engine),
            patch("magi.api.routers.personality_config.resolve_avatar_public_url", return_value=""),
            patch("magi.api.routers.personality_config.get_runtime_paths") as mock_paths,
        ):
            mock_paths.return_value.growth_db_path = "/tmp/test/growth.db"
            mock_paths.return_value.persona_registry_db_path = "/tmp/test/persona_registry.db"

            resp = await api_get_greeting()

        assert resp.data["needs_bootstrap"] is False
        assert resp.data["bootstrap_opening"] is None

    @pytest.mark.asyncio
    async def test_greeting_bootstrap_graceful_on_error(self):
        """Bootstrap check failure should not break the greeting."""
        config = _mock_config(with_bootstrap=False)

        with (
            patch("magi.api.routers.personality_config.get_current_personality_name", return_value="testbot"),
            patch("magi.api.routers.personality_config.get_current_personality_config", return_value=config),
            patch("magi.api.routers.personality_config.GrowthMemoryEngine", side_effect=RuntimeError("DB error")),
            patch("magi.api.routers.personality_config.resolve_avatar_public_url", return_value=""),
            patch("magi.api.routers.personality_config.get_runtime_paths") as mock_paths,
        ):
            mock_paths.return_value.growth_db_path = "/tmp/test/growth.db"
            mock_paths.return_value.persona_registry_db_path = "/tmp/test/persona_registry.db"

            resp = await api_get_greeting()

        assert resp.success is True
        assert resp.data["needs_bootstrap"] is False


class TestBootstrapInitEndpoint:
    """POST /bootstrap/init endpoint tests."""

    @pytest.mark.asyncio
    async def test_bootstrap_init_injects_opening(self):
        mock_engine = AsyncMock()
        mock_engine.init = AsyncMock()
        mock_engine.get_milestones = AsyncMock(return_value=[])

        config = _mock_config(with_bootstrap=True)

        mock_chat_store = AsyncMock()
        mock_chat_store.upsert_turn = AsyncMock()
        mock_chat_store.next_sequence_no = AsyncMock(return_value=1)
        mock_chat_store.append_message = AsyncMock()
        mock_chat_store.bump_history_version = AsyncMock(return_value=1)

        mock_trace_store = AsyncMock()
        mock_trace_store.append_notification = AsyncMock(return_value=1)

        with (
            patch("magi.api.routers.personality_config.get_current_personality_name", return_value="testbot"),
            patch("magi.api.routers.personality_config.GrowthMemoryEngine", return_value=mock_engine),
            patch("magi.api.routers.personality_config.get_runtime_paths") as mock_paths,
            patch("magi.personality.bootstrap_service.resolve_persona_config", new_callable=AsyncMock, return_value=config),
            patch("magi.core.runtime_bindings.require_chat_store", return_value=mock_chat_store),
            patch("magi.core.runtime_bindings.require_runtime_trace_store", return_value=mock_trace_store),
        ):
            mock_paths.return_value.growth_db_path = "/tmp/test/growth.db"
            mock_paths.return_value.persona_registry_db_path = "/tmp/test/persona_registry.db"

            request = BootstrapInitRequest(session_id="sess_001")
            resp = await api_bootstrap_init(request)

        assert resp.success is True
        assert resp.data["bootstrap_active"] is True
        assert resp.data["opening"] == "Hey, first time here."
        mock_chat_store.upsert_turn.assert_called_once()
        mock_chat_store.append_message.assert_called_once()
        mock_trace_store.append_notification.assert_called_once()

    @pytest.mark.asyncio
    async def test_bootstrap_init_already_completed(self):
        milestone = MagicMock()
        milestone.metadata = {"persona_name": "testbot"}
        mock_engine = AsyncMock()
        mock_engine.init = AsyncMock()
        mock_engine.get_milestones = AsyncMock(return_value=[milestone])

        with (
            patch("magi.api.routers.personality_config.get_current_personality_name", return_value="testbot"),
            patch("magi.api.routers.personality_config.GrowthMemoryEngine", return_value=mock_engine),
            patch("magi.api.routers.personality_config.get_runtime_paths") as mock_paths,
        ):
            mock_paths.return_value.growth_db_path = "/tmp/test/growth.db"
            mock_paths.return_value.persona_registry_db_path = "/tmp/test/persona_registry.db"

            request = BootstrapInitRequest(session_id="sess_001")
            resp = await api_bootstrap_init(request)

        assert resp.data["bootstrap_active"] is False


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

        mock_chat_store = AsyncMock()
        mock_chat_store.create_user_turn = AsyncMock(return_value=MagicMock(message_id="msg_user"))
        mock_chat_store.upsert_turn = AsyncMock()
        mock_chat_store.next_sequence_no = AsyncMock(return_value=2)
        mock_chat_store.append_message = AsyncMock()
        mock_chat_store.bump_history_version = AsyncMock(return_value=1)

        mock_trace_store = AsyncMock()
        mock_trace_store.append_notification = AsyncMock(return_value=1)

        with (
            patch("magi.api.routers.personality_config.get_current_personality_name", return_value="testbot"),
            patch("magi.api.routers.personality_config.GrowthMemoryEngine", return_value=mock_engine),
            patch("magi.api.routers.personality_config.get_runtime_paths") as mock_paths,
            patch("magi.personality.bootstrap_service.resolve_persona_config", new_callable=AsyncMock, return_value=config),
            patch("magi.personality.bootstrap_service.require_scenario_llm_pool") as mock_pool,
            patch("magi.core.runtime_bindings.require_chat_store", return_value=mock_chat_store),
            patch("magi.core.runtime_bindings.require_runtime_trace_store", return_value=mock_trace_store),
        ):
            mock_paths.return_value.growth_db_path = "/tmp/test/growth.db"
            mock_paths.return_value.persona_registry_db_path = "/tmp/test/persona_registry.db"
            mock_pool.return_value.get.return_value.chat = AsyncMock(return_value="Nice to meet you!")

            request = BootstrapMessageRequest(
                user_message="I'm Alice",
                history=[],
                session_id="sess_001",
            )
            resp = await api_bootstrap_message(request)

        assert resp.success is True
        assert resp.data["reply"] == "Nice to meet you!"
        # Both user turn and assistant reply should be persisted
        mock_chat_store.create_user_turn.assert_called_once()
        mock_chat_store.append_message.assert_called_once()
        mock_trace_store.append_notification.assert_called_once()

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
        ):
            mock_paths.return_value.growth_db_path = "/tmp/test/growth.db"
            mock_paths.return_value.persona_registry_db_path = "/tmp/test/persona_registry.db"

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
            patch("magi.personality.persona_journal_service.resolve_persona_config", new_callable=AsyncMock, return_value=config),
            patch("magi.personality.persona_journal_service.PersonaJournalService._call_llm",
                  new_callable=AsyncMock, return_value="I felt calm today."),
        ):
            mock_paths.return_value.growth_db_path = "/tmp/test/growth.db"
            mock_paths.return_value.persona_registry_db_path = "/tmp/test/persona_registry.db"

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
            patch("magi.personality.persona_journal_service.resolve_persona_config", new_callable=AsyncMock, return_value=None),
            patch("magi.personality.persona_journal_service.PersonaJournalService._call_llm",
                  new_callable=AsyncMock, return_value=None),
        ):
            mock_paths.return_value.growth_db_path = "/tmp/test/growth.db"
            mock_paths.return_value.persona_registry_db_path = "/tmp/test/persona_registry.db"

            request = JournalReflectRequest()
            resp = await api_journal_reflect(request)

        assert resp.success is False
