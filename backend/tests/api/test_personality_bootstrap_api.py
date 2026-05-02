"""Tests for personality bootstrap and journal API endpoints."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from magi.api.routers.personality_config import (
    BootstrapInitRequest,
    JournalReflectRequest,
    _wait_for_bootstrap_runtime_ready,
    api_bootstrap_init,
    api_get_greeting,
    api_journal_reflect,
)


@pytest.fixture(autouse=True)
def _reset_growth_engine():
    """Reset the cached growth engine between tests."""
    import magi.personality.bootstrap_service as mod

    original = mod._growth_engine_instance
    mod._growth_engine_instance = None
    yield
    mod._growth_engine_instance = original


def _mock_config(*, with_bootstrap: bool = True):
    config = MagicMock()
    config.name = "TestBot"
    config.avatar = "avatar.png"
    config.identity_core.identity_statement = "A test persona."
    config.idiolect.sentence_style = "Neutral"
    if with_bootstrap:
        config.bootstrap = MagicMock()
        config.bootstrap.opening_line = "Hey, first time here."
        config.bootstrap.style_instruction = "Speak naturally."
        config.bootstrap.max_rounds = 3
    else:
        config.bootstrap = None
    return config


class TestGreetingBootstrapStatus:
    """Greeting endpoint includes bootstrap status but does not generate an opening."""

    @pytest.mark.asyncio
    async def test_greeting_includes_needs_bootstrap_without_generating_opening(self):
        config = _mock_config(with_bootstrap=True)
        bootstrap_svc = SimpleNamespace(
            needs_bootstrap=AsyncMock(return_value=True),
            needs_bootstrap_init=AsyncMock(return_value=True),
            get_opening=AsyncMock(side_effect=AssertionError("/greeting should not generate opening text")),
        )

        with (
            patch("magi.api.routers.personality_config.get_current_personality_name", return_value="testbot"),
            patch("magi.api.routers.personality_config._load_current_config", new_callable=AsyncMock, return_value=config),
            patch("magi.api.routers.personality_config._resolve_persona_id", new_callable=AsyncMock, return_value="persona-1"),
            patch("magi.api.routers.personality_config._get_bootstrap_service", new_callable=AsyncMock, return_value=bootstrap_svc),
            patch("magi.api.routers.personality_config.resolve_avatar_public_url", return_value="/static/avatars/avatar.png"),
        ):
            resp = await api_get_greeting()

        assert resp.data == {
            "name": "TestBot",
            "avatar": "/static/avatars/avatar.png",
            "needs_bootstrap": True,
            "needs_bootstrap_init": True,
            "bootstrap_completed": False,
        }
        bootstrap_svc.needs_bootstrap_init.assert_awaited_once()
        bootstrap_svc.get_opening.assert_not_called()

    @pytest.mark.asyncio
    async def test_greeting_bootstrap_graceful_on_error(self):
        config = _mock_config(with_bootstrap=False)

        with (
            patch("magi.api.routers.personality_config.get_current_personality_name", return_value="testbot"),
            patch("magi.api.routers.personality_config._load_current_config", new_callable=AsyncMock, return_value=config),
            patch("magi.api.routers.personality_config._get_bootstrap_service", new_callable=AsyncMock, side_effect=RuntimeError("DB error")),
            patch("magi.api.routers.personality_config.resolve_avatar_public_url", return_value=""),
        ):
            resp = await api_get_greeting()

        assert resp.success is True
        assert resp.data["needs_bootstrap"] is False


class TestBootstrapInitEndpoint:
    """POST /bootstrap/init endpoint tests."""

    @pytest.mark.asyncio
    async def test_wait_for_bootstrap_runtime_ready_ignores_startup_state_until_llm_is_ready(self):
        snapshots = [
            {
                "llm_ready": False,
                "startup_state": "ready",
                "deferred_reason": None,
            },
            {
                "llm_ready": True,
                "startup_state": "ready",
                "deferred_reason": None,
            },
        ]

        async def _fake_snapshot():
            return snapshots.pop(0)

        with (
            patch("magi.api.routers.personality_config._get_runtime_status_snapshot", new_callable=AsyncMock, side_effect=_fake_snapshot),
            patch("magi.api.routers.personality_config.asyncio.sleep", new_callable=AsyncMock) as sleep_mock,
        ):
            runtime_status = await _wait_for_bootstrap_runtime_ready()

        assert runtime_status["llm_ready"] is True
        sleep_mock.assert_awaited_once_with(0.2)

    @pytest.mark.asyncio
    async def test_bootstrap_init_injects_opening_and_returns_runtime_state(self):
        bootstrap_svc = SimpleNamespace(
            needs_bootstrap=AsyncMock(return_value=True),
            needs_bootstrap_init=AsyncMock(return_value=True),
            get_opening=AsyncMock(return_value="Hey, first time here."),
            mark_bootstrap_started=AsyncMock(),
        )

        with (
            patch("magi.api.routers.personality_config.get_current_personality_name", return_value="testbot"),
            patch("magi.api.routers.personality_config._resolve_persona_id", new_callable=AsyncMock, return_value="persona-1"),
            patch("magi.api.routers.personality_config._get_bootstrap_service", new_callable=AsyncMock, return_value=bootstrap_svc),
            patch(
                "magi.api.routers.personality_config._wait_for_bootstrap_runtime_ready",
                new_callable=AsyncMock,
                return_value={
                    "llm_ready": True,
                    "startup_state": "ready",
                    "deferred_reason": None,
                },
            ),
            patch(
                "magi.api.routers.personality_config._persist_bootstrap_assistant_message",
                new_callable=AsyncMock,
                return_value="msg_001",
            ) as persist_message,
        ):
            request = BootstrapInitRequest(session_id="sess_001")
            resp = await api_bootstrap_init(request)

        assert resp.success is True
        assert resp.data == {
            "bootstrap_active": False,
            "opening": "Hey, first time here.",
            "needs_bootstrap_init": False,
            "bootstrap_completed": True,
            "startup_state": "ready",
            "deferred_reason": None,
        }
        bootstrap_svc.needs_bootstrap_init.assert_awaited_once()
        bootstrap_svc.get_opening.assert_awaited_once()
        persist_message.assert_awaited_once()
        bootstrap_svc.mark_bootstrap_started.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_bootstrap_init_returns_success_when_runtime_bindings_are_still_starting(self):
        bootstrap_svc = SimpleNamespace(
            needs_bootstrap=AsyncMock(return_value=True),
            needs_bootstrap_init=AsyncMock(return_value=True),
            get_opening=AsyncMock(return_value="Hey, first time here."),
            mark_bootstrap_started=AsyncMock(),
        )

        with (
            patch("magi.api.routers.personality_config.get_current_personality_name", return_value="testbot"),
            patch("magi.api.routers.personality_config._resolve_persona_id", new_callable=AsyncMock, return_value="persona-1"),
            patch("magi.api.routers.personality_config._get_bootstrap_service", new_callable=AsyncMock, return_value=bootstrap_svc),
            patch(
                "magi.api.routers.personality_config._wait_for_bootstrap_runtime_ready",
                new_callable=AsyncMock,
                return_value={
                    "llm_ready": False,
                    "startup_state": "deferred",
                    "deferred_reason": "llm_selection_pending",
                },
            ),
            patch(
                "magi.api.routers.personality_config._persist_bootstrap_assistant_message",
                new_callable=AsyncMock,
                side_effect=RuntimeError("chat_store binding is not initialized"),
            ),
        ):
            request = BootstrapInitRequest(session_id="sess_001")
            resp = await api_bootstrap_init(request)

        assert resp.success is True
        assert resp.data == {
            "bootstrap_active": False,
            "opening": "Hey, first time here.",
            "needs_bootstrap_init": False,
            "bootstrap_completed": True,
            "startup_state": "deferred",
            "deferred_reason": "llm_selection_pending",
        }
        bootstrap_svc.mark_bootstrap_started.assert_not_called()

    @pytest.mark.asyncio
    async def test_bootstrap_init_skips_when_opening_already_injected(self):
        bootstrap_svc = SimpleNamespace(needs_bootstrap_init=AsyncMock(return_value=False))

        with (
            patch("magi.api.routers.personality_config.get_current_personality_name", return_value="testbot"),
            patch("magi.api.routers.personality_config._resolve_persona_id", new_callable=AsyncMock, return_value="persona-1"),
            patch("magi.api.routers.personality_config._get_bootstrap_service", new_callable=AsyncMock, return_value=bootstrap_svc),
        ):
            request = BootstrapInitRequest(session_id="sess_001")
            resp = await api_bootstrap_init(request)

        assert resp.data["bootstrap_active"] is False
        assert resp.data["opening"] is None
        assert resp.data["needs_bootstrap_init"] is False
        assert resp.data["bootstrap_completed"] is True


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
        config.name = "TestBot"
        config.description = "Tester"

        with (
            patch("magi.api.routers.personality_config.get_current_personality_name", return_value="testbot"),
            patch("magi.api.routers.personality_config.get_shared_growth_engine", new_callable=AsyncMock, return_value=mock_engine),
            patch("magi.personality.persona_journal_service.resolve_persona_config", new_callable=AsyncMock, return_value=config),
            patch(
                "magi.personality.persona_journal_service.PersonaJournalService._call_llm",
                new_callable=AsyncMock,
                return_value="I felt calm today.",
            ),
        ):
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
            patch(
                "magi.personality.persona_journal_service.PersonaJournalService._call_llm",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            mock_paths.return_value.growth_db_path = "/tmp/test/growth.db"
            mock_paths.return_value.persona_registry_db_path = "/tmp/test/persona_registry.db"

            request = JournalReflectRequest()
            resp = await api_journal_reflect(request)

        assert resp.success is False
