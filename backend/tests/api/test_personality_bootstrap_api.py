"""Tests for personality bootstrap and journal API endpoints."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

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


@pytest_asyncio.fixture
async def selected_persona(runtime_paths_with_schema, monkeypatch):
    import json
    from magi.api.routers import personality_config
    from magi.personality.persona_repository import PersonaRepository

    monkeypatch.setattr(personality_config, "get_runtime_paths", lambda: runtime_paths_with_schema)
    repo = PersonaRepository(str(runtime_paths_with_schema.persona_registry_db_path))
    await repo.init()
    persona_id = await repo.create(
        config_json=json.dumps({"name": "TestBot", "avatar": "avatar.png"}),
        slug="testbot", locale="en",
    )
    await repo.set_active(persona_id)
    return await repo.get(persona_id)


class TestGreetingBootstrapStatus:
    """Greeting reads saved identity without waiting for optional activation."""

    @pytest.mark.asyncio
    async def test_greeting_before_runtime_activation_uses_saved_identity(self, selected_persona):
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient
        from magi.api.routers.personality_config import personality_config_router
        from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router

        bootstrap_svc = SimpleNamespace(
            needs_bootstrap_init=AsyncMock(return_value=True),
            get_opening=AsyncMock(side_effect=AssertionError("Greeting must not generate an opening")),
        )
        app = FastAPI()
        app.include_router(_build_public_router(
            personality_config_router, _PUBLIC_ROUTE_METHODS["personality_config"],
        ), prefix="/api/personality")
        with (
            patch("magi.api.routers.personality_config.get_current_personality_name", return_value=""),
            patch("magi.api.routers.personality_config.get_current_personality_config", return_value=None),
            patch("magi.api.routers.personality_config._get_bootstrap_service", new_callable=AsyncMock, return_value=bootstrap_svc),
            patch("magi.api.routers.personality_config.resolve_avatar_public_url", return_value="/static/avatars/avatar.png"),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get("/api/personality/greeting")
        assert response.status_code == 200
        assert response.json()["data"] == {
            "name": "TestBot",
            "avatar": "/static/avatars/avatar.png",
            "needs_bootstrap": True,
            "needs_bootstrap_init": True,
            "bootstrap_completed": False,
        }
        bootstrap_svc.needs_bootstrap_init.assert_awaited_once_with("testbot", persona_id=selected_persona.persona_id)
        bootstrap_svc.get_opening.assert_not_called()

    @pytest.mark.asyncio
    async def test_greeting_bootstrap_graceful_on_error(self, selected_persona):
        with patch("magi.api.routers.personality_config._get_bootstrap_service", new_callable=AsyncMock, side_effect=RuntimeError("DB error")):
            resp = await api_get_greeting()
        assert resp.success is True
        assert resp.data["name"] == "TestBot"
        assert resp.data["needs_bootstrap"] is False

    @pytest.mark.asyncio
    async def test_no_active_persona_does_not_claim_a_default_identity(self, selected_persona):
        from fastapi import HTTPException
        from magi.api.routers import personality_config

        repo = personality_config.PersonaRepository(str(personality_config.get_runtime_paths().persona_registry_db_path))
        await repo.clear_active()
        with pytest.raises(HTTPException) as error:
            await api_get_greeting()
        assert error.value.status_code == 503


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
        steps = []
        bootstrap_svc = SimpleNamespace(
            needs_bootstrap=AsyncMock(return_value=True),
            needs_bootstrap_init=AsyncMock(return_value=True),
            get_opening=AsyncMock(return_value="Hey, first time here."),
            mark_bootstrap_started=AsyncMock(side_effect=lambda **_: steps.append("started")),
        )

        with (
            patch(
                "magi.api.routers.personality_config.get_current_personality_name",
                return_value="testbot",
            ),
            patch(
                "magi.api.routers.personality_config._resolve_persona_id",
                new_callable=AsyncMock,
                return_value="persona-1",
            ),
            patch(
                "magi.api.routers.personality_config._get_bootstrap_service",
                new_callable=AsyncMock,
                return_value=bootstrap_svc,
            ),
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
                side_effect=lambda **_: steps.append("persisted") or "msg_001",
            ) as persist_message,
        ):
            request = BootstrapInitRequest(session_id="sess_001", user_id="user-canary")
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
        bootstrap_svc.needs_bootstrap_init.assert_awaited_once_with("testbot", persona_id="persona-1")
        bootstrap_svc.get_opening.assert_awaited_once_with("testbot", persona_id="persona-1")
        turn_id = persist_message.await_args.kwargs["turn_id"]
        assert turn_id.startswith("turn_bs_")
        persist_message.assert_awaited_once_with(
            session_id="sess_001",
            user_id="user-canary",
            turn_id=turn_id,
            content="Hey, first time here.",
        )
        bootstrap_svc.mark_bootstrap_started.assert_awaited_once_with(
            persona_name="testbot",
            persona_id="persona-1",
            user_id="user-canary",
            session_id="sess_001",
            turn_id=turn_id,
            message_id="msg_001",
        )
        assert steps == ["persisted", "started"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "failure,expected_status",
        [("chat_store binding is not initialized", 503), ("injected write failure", 500)],
    )
    async def test_bootstrap_failure_remains_retryable_until_persistence_succeeds(
        self, runtime_paths_with_schema, monkeypatch, failure, expected_status
    ):
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient
        from magi.api.routers import personality_config
        from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
        from magi.personality.bootstrap_service import BootstrapDialogueService
        from magi.personality.growth_memory import GrowthMemoryEngine, MilestoneType

        growth = GrowthMemoryEngine(str(runtime_paths_with_schema.growth_db_path))
        await growth.init()
        bootstrap = BootstrapDialogueService(growth_engine=growth)
        monkeypatch.setattr(bootstrap, "get_opening", AsyncMock(return_value="Hey, first time here."))
        monkeypatch.setattr(personality_config, "get_current_personality_name", lambda: "testbot")
        monkeypatch.setattr(
            personality_config, "_resolve_persona_id", AsyncMock(return_value="persona-1")
        )
        monkeypatch.setattr(
            personality_config, "_get_bootstrap_service", AsyncMock(return_value=bootstrap)
        )
        monkeypatch.setattr(
            personality_config,
            "_wait_for_bootstrap_runtime_ready",
            AsyncMock(
                return_value={
                    "llm_ready": False,
                    "startup_state": "deferred",
                    "deferred_reason": "llm_selection_pending",
                }
            ),
        )
        persist = AsyncMock(side_effect=[RuntimeError(failure), "message-persisted"])
        monkeypatch.setattr(personality_config, "_persist_bootstrap_assistant_message", persist)
        app = FastAPI()
        app.include_router(
            _build_public_router(
                personality_config.personality_config_router,
                _PUBLIC_ROUTE_METHODS["personality_config"],
            ),
            prefix="/api/personality",
        )
        request = {"session_id": "session-retry", "user_id": "user-retry"}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            failed = await client.post("/api/personality/bootstrap/init", json=request)
            assert failed.status_code == expected_status
            assert await bootstrap.needs_bootstrap_init("testbot", persona_id="persona-1") is True
            assert await growth.get_milestones(milestone_type=MilestoneType.BOOTSTRAP_STARTED) == []
            retried = await client.post("/api/personality/bootstrap/init", json=request)
            assert retried.status_code == 200
            assert retried.json()["data"]["bootstrap_completed"] is True
            assert retried.json()["data"]["opening"] == "Hey, first time here."
            repeated = await client.post("/api/personality/bootstrap/init", json=request)
            assert repeated.status_code == 200
            assert repeated.json()["data"]["opening"] is None
        assert persist.await_count == 2
        for call in persist.await_args_list:
            assert {k: v for k, v in call.kwargs.items() if k != "turn_id"} == {
                **request,
                "content": "Hey, first time here.",
            }
        reloaded = GrowthMemoryEngine(str(runtime_paths_with_schema.growth_db_path))
        milestones = await reloaded.get_milestones(milestone_type=MilestoneType.BOOTSTRAP_STARTED)
        assert len(milestones) == 1
        assert milestones[0].metadata == {
            **request,
            "persona_name": "testbot",
            "persona_id": "persona-1",
            "turn_id": persist.await_args.kwargs["turn_id"],
            "message_id": "message-persisted",
        }
        assert (
            await BootstrapDialogueService(growth_engine=reloaded).needs_bootstrap_init(
                "testbot", persona_id="persona-1"
            )
            is False
        )

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
