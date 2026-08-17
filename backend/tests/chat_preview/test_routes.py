"""HTTP API contract tests for POST /api/chat/preview."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers import chat_preview_routes
from magi.api.routers.chat_preview_routes import build_default_chat_preview_router
from magi.config.models import (
    LLMProviderSettings,
    LLMScenario,
    LLMSelectionSettings,
    LLMSettings,
)
from magi.personality.loader import PersonalityConfig


def _persona_config(name: str = "Nova") -> PersonalityConfig:
    return PersonalityConfig.from_dict(
        {
            "name": name,
            "identity_core": {
                "identity_statement": "A calm, curious companion.",
                "values_loved": ["honesty"],
                "attention_biases": ["the user's emotional tone"],
            },
            "idiolect": {
                "sentence_style": "Short and warm.",
                "structural_quirks": ["Uses short chat messages."],
                "chattiness": 0.8,
            },
            "registers": {
                "chat": {
                    "description": "Ordinary conversation",
                    "behavior": "Use short sentences and a quick rhythm.",
                    "examples": ["[User: hi]\n* Good: hey."],
                }
            },
        }
    )


def _llm_settings(api_key: str) -> LLMSettings:
    provider = LLMProviderSettings(
        enabled=True,
        provider_type="openai",
        api_key=api_key,
    )
    provider.services.chat.api_key = api_key
    return LLMSettings(
        providers={"openai": provider},
        selections={
            LLMScenario.CONTEXT_DECIDER.value: LLMSelectionSettings(
                provider_id="openai",
                model="gpt-5.6-mini",
            ),
            LLMScenario.CORE.value: LLMSelectionSettings(
                provider_id="openai",
                model="gpt-5.6",
            ),
        },
    )


@pytest.fixture
def app_with_preview():
    async def fake_llm(*, system_prompt, messages, model):
        for chunk in ["hi", " ", "there"]:
            yield chunk

    def fake_loader(seed_slug: str, locale: str) -> PersonalityConfig:
        if seed_slug == "ghost":
            raise ValueError("unknown seed: ghost")
        return _persona_config(f"{seed_slug}-{locale}")

    # The LLM deps now receive the request's optional ``llm_override``; the
    # fakes ignore it but must accept the positional arg.
    def fake_core_model(llm_override=None) -> str:
        return "test-core-model"

    app = FastAPI()
    app.include_router(
        build_default_chat_preview_router(
            persona_loader_dep=lambda: fake_loader,
            llm_call_dep=lambda _override=None: fake_llm,
            core_model_dep=fake_core_model,
        ),
    )
    return app


def test_post_preview_returns_delivery_segments(app_with_preview) -> None:
    client = TestClient(app_with_preview)
    response = client.post(
        "/chat/preview",
        json={
            "seed_slug": "nova",
            "history": [],
            "message": {"role": "user", "content": "hello"},
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "segments": [{"content": "hi there", "delay_ms": 0}],
    }


def test_post_preview_returns_delays_for_buffered_desktop_transport(monkeypatch) -> None:
    from magi.agent.response_rhythm import ResponseRhythmPlanner

    async def fake_llm(*, system_prompt, messages, model):
        yield "first short message‖second short message"

    monkeypatch.setattr(
        ResponseRhythmPlanner,
        "_is_enabled",
        staticmethod(lambda: True),
    )
    app = FastAPI()
    app.include_router(
        build_default_chat_preview_router(
            persona_loader_dep=lambda: (lambda slug, locale: _persona_config(slug)),
            llm_call_dep=lambda _override=None: fake_llm,
            core_model_dep=lambda _override=None: "core-model",
        ),
    )
    client = TestClient(app)
    response = client.post(
        "/chat/preview",
        json={
            "seed_slug": "nova",
            "history": [],
            "message": {"role": "user", "content": "hello"},
        },
    )

    assert response.status_code == 200
    segments = response.json()["segments"]
    assert segments[0] == {"content": "first short message", "delay_ms": 0}
    assert segments[1]["content"] == "second short message"
    assert 1000 <= segments[1]["delay_ms"] <= 4000


def test_post_preview_validates_seed_slug(app_with_preview) -> None:
    client = TestClient(app_with_preview)
    response = client.post(
        "/chat/preview",
        json={
            "seed_slug": "ghost",
            "history": [],
            "message": {"role": "user", "content": "hi"},
        },
    )
    assert response.status_code == 400
    assert "unknown seed" in response.text


def test_post_preview_rejects_empty_message(app_with_preview) -> None:
    client = TestClient(app_with_preview)
    response = client.post(
        "/chat/preview",
        json={
            "seed_slug": "nova",
            "history": [],
            "message": {"role": "user", "content": ""},
        },
    )
    assert response.status_code == 422  # Pydantic validation


def test_post_preview_caps_history_length(app_with_preview) -> None:
    """History longer than 20 turns is rejected to bound LLM cost per request."""
    client = TestClient(app_with_preview)
    too_long = [{"role": "user", "content": "x"}] * 21
    response = client.post(
        "/chat/preview",
        json={
            "seed_slug": "nova",
            "history": too_long,
            "message": {"role": "user", "content": "hi"},
        },
    )
    assert response.status_code == 422


def test_post_preview_threads_llm_override_to_deps() -> None:
    """An unsaved ``llm_override`` from onboarding reaches both LLM deps."""
    seen: dict[str, object] = {}

    async def fake_llm(*, system_prompt, messages, model):
        yield "ok"

    def llm_call_dep(override=None):
        seen["llm_call_override"] = override
        return fake_llm

    def core_model_dep(override=None) -> str:
        seen["core_model_override"] = override
        return "override-core-model"

    app = FastAPI()
    app.include_router(
        build_default_chat_preview_router(
            persona_loader_dep=lambda: (lambda slug, locale: _persona_config(slug)),
            llm_call_dep=llm_call_dep,
            core_model_dep=core_model_dep,
        ),
    )

    override = {
        "providers": {
            "openai": {
                "enabled": True,
                "provider_type": "openai",
                "api_key": "sk-test",
            }
        },
        "selections": {
            "core": {"provider_id": "openai", "model": "gpt-4o"},
            "context_decider": {"provider_id": "openai", "model": "gpt-4o-mini"},
        },
    }
    client = TestClient(app)
    with client.stream(
        "POST",
        "/chat/preview",
        json={
            "seed_slug": "nova",
            "history": [],
            "message": {"role": "user", "content": "hi"},
            "llm_override": override,
        },
    ) as response:
        assert response.status_code == 200
        b"".join(response.iter_bytes())

    # Both deps received the parsed LLMSettings override (not None).
    assert seen["llm_call_override"] is not None
    assert seen["core_model_override"] is not None
    assert seen["core_model_override"].selections["core"].model == "gpt-4o"


def test_post_preview_restores_masked_llm_override_before_resolving_deps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, LLMSettings] = {}

    async def fake_llm(*, system_prompt, messages, model):
        _ = system_prompt, messages, model
        yield "ok"

    def llm_call_dep(override=None):
        seen["llm_call_override"] = override
        return fake_llm

    def core_model_dep(override=None) -> str:
        seen["core_model_override"] = override
        return "gpt-5.6"

    monkeypatch.setattr(
        chat_preview_routes,
        "get_config",
        lambda: SimpleNamespace(llm=_llm_settings("sk-backend-owned")),
    )
    app = FastAPI()
    app.include_router(
        build_default_chat_preview_router(
            persona_loader_dep=lambda: (lambda slug, locale: _persona_config(slug)),
            llm_call_dep=llm_call_dep,
            core_model_dep=core_model_dep,
        ),
    )

    response = TestClient(app).post(
        "/chat/preview",
        json={
            "seed_slug": "nova",
            "history": [],
            "message": {"role": "user", "content": "hi"},
            "llm_override": _llm_settings("***").model_dump(mode="json"),
        },
    )

    assert response.status_code == 200
    assert (
        seen["llm_call_override"].providers["openai"].services.chat.api_key
        == "sk-backend-owned"
    )
    assert (
        seen["core_model_override"].providers["openai"].services.chat.api_key
        == "sk-backend-owned"
    )


def _capture_prompt_app(captured: dict) -> FastAPI:
    """Build a preview app whose fake LLM records the system prompt it gets."""

    async def fake_llm(*, system_prompt, messages, model):
        captured["system_prompt"] = system_prompt
        yield "ok"

    def fake_loader(seed_slug: str, locale: str) -> PersonalityConfig:
        if not seed_slug:
            raise ValueError("unknown seed: ")
        return _persona_config(f"{seed_slug}-{locale}")

    app = FastAPI()
    app.include_router(
        build_default_chat_preview_router(
            persona_loader_dep=lambda: fake_loader,
            llm_call_dep=lambda _override=None: fake_llm,
            core_model_dep=lambda _override=None: "core-model",
        ),
    )
    return app


def test_post_preview_accepts_complete_persona_override() -> None:
    """An unsaved persona uses the normal prompt with its complete behavior config."""
    captured: dict[str, str] = {}
    client = TestClient(_capture_prompt_app(captured))
    with client.stream(
        "POST",
        "/chat/preview",
        json={
            "history": [],
            "message": {"role": "user", "content": "hi"},
            "persona_override": {
                "name": "Aria",
                "identity_core": {
                    "identity_statement": "a calm, curious companion",
                    "values_loved": ["honesty"],
                },
                "idiolect": {
                    "sentence_style": "short and warm",
                    "structural_quirks": ["Never turns casual chat into a list."],
                    "chattiness": 0.9,
                },
                "registers": {
                    "chat": {
                        "description": "ordinary chat",
                        "behavior": "Use short sentences and quick particles.",
                        "examples": ["[User: hello]\n* Good: hey."],
                    }
                },
            },
        },
    ) as response:
        assert response.status_code == 200
        b"".join(response.iter_bytes())

    prompt = captured["system_prompt"]
    # The complete override (not the seed loader) supplied the normal prompt.
    assert "# System Definition" in prompt
    assert "# Persona Runtime Plan" in prompt
    assert "# Persona Turn Steer" in prompt
    assert "Aria" in prompt
    assert "a calm, curious companion" in prompt
    assert "short and warm" in prompt
    assert "Use short sentences and quick particles." in prompt
    assert "[User: hello]" in prompt
    assert "Most replies are 1-3 lines." in prompt
    assert "# Tool Use Guidance" not in prompt
    assert "Persona preview scene" not in prompt
    assert "seed prompt" not in prompt


class _FakeBridge:
    """Captures the kwargs and yields a mixed reasoning/text/usage stream."""

    def __init__(self) -> None:
        self.kwargs: dict = {}

    def chat_response_stream(self, **kwargs):
        self.kwargs = kwargs

        async def _gen():
            yield SimpleNamespace(kind="reasoning_delta", text="(thinking...)")
            yield SimpleNamespace(kind="text_delta", text="Hello")
            yield SimpleNamespace(kind="text_delta", text=" there")
            yield SimpleNamespace(kind="usage", text=None)

        return _gen()


@pytest.mark.asyncio
async def test_stream_preview_text_yields_visible_text_with_thinking_off() -> None:
    """The preview streams only visible text_delta and requests thinking OFF."""
    from magi.api.routers.chat_preview_routes import _stream_preview_text
    from magi.config.models import ThinkingDepth

    bridge = _FakeBridge()
    out = [
        chunk
        async for chunk in _stream_preview_text(
            bridge, system_prompt="sys", messages=[{"role": "user", "content": "hi"}]
        )
    ]

    # Reasoning + usage events are dropped; only visible text is yielded.
    assert out == ["Hello", " there"]
    # Thinking is disabled and the system prompt is forwarded.
    assert bridge.kwargs["thinking_depth"] == ThinkingDepth.NONE
    assert bridge.kwargs["system_prompt"] == "sys"
    assert bridge.kwargs["messages"] == [{"role": "user", "content": "hi"}]


def test_resolve_persona_config_reads_locale_preset() -> None:
    """The production resolver reads personalities/{locale}/{slug}.json.

    Regression: the old loader searched only non-locale paths, so real seeds
    (which live under personalities/{locale}/) raised 'unknown seed'.
    """
    from magi.api.routers.chat_preview_routes import _resolve_persona_config

    config = _resolve_persona_config("echo_ai_assistant", "zh")
    assert config.name
    assert config.identity_core.identity_statement
    assert config.idiolect.sentence_style


@pytest.mark.asyncio
async def test_seed_preview_uses_normal_first_chat_prompt() -> None:
    """Bundled personas use normal identity, planner, examples, and empty context."""
    from magi.api.routers.chat_preview_routes import _resolve_persona_config
    from magi.chat_preview import build_preview_system_prompt

    config = _resolve_persona_config("seven_hacker", "zh")
    prompt = await build_preview_system_prompt(
        persona_config=config,
        user_message="第一次见面，你会怎么和我相处？",
    )

    assert "# System Definition" in prompt
    assert "# Persona Runtime Plan" in prompt
    assert "# Persona Turn Steer" in prompt
    assert "Most replies are 1-3 lines." in prompt
    assert "默认 1-3 句" in prompt
    assert "不用bullet list处理日常对话" in prompt
    assert "## Relevant Persona Examples" in prompt
    assert "* Good:" in prompt
    assert "# Memory Library" in prompt
    assert "* (empty)" in prompt
    assert "# Tool Use Guidance" not in prompt
    assert "Persona preview scene" not in prompt
    assert "seven_guard_down" not in prompt
    assert "当场认大哥" not in prompt


def test_resolve_persona_config_unknown_seed_raises() -> None:
    from magi.api.routers.chat_preview_routes import _resolve_persona_config

    with pytest.raises(ValueError):
        _resolve_persona_config("does_not_exist", "zh")


def test_post_preview_threads_locale_to_loader() -> None:
    """The request's ``locale`` selects which preset folder the seed resolves in."""
    seen: dict[str, str] = {}

    async def fake_llm(*, system_prompt, messages, model):
        yield "ok"

    def fake_loader(seed_slug: str, locale: str) -> PersonalityConfig:
        seen["seed_slug"] = seed_slug
        seen["locale"] = locale
        return _persona_config(seed_slug)

    app = FastAPI()
    app.include_router(
        build_default_chat_preview_router(
            persona_loader_dep=lambda: fake_loader,
            llm_call_dep=lambda _override=None: fake_llm,
            core_model_dep=lambda _override=None: "core-model",
        ),
    )
    client = TestClient(app)
    with client.stream(
        "POST",
        "/chat/preview",
        json={
            "seed_slug": "sumen_listener",
            "locale": "zh",
            "history": [],
            "message": {"role": "user", "content": "hi"},
        },
    ) as response:
        assert response.status_code == 200
        b"".join(response.iter_bytes())

    assert seen == {"seed_slug": "sumen_listener", "locale": "zh"}


def test_post_preview_requires_seed_or_override() -> None:
    """A request with neither seed_slug nor persona_override is a 400."""
    captured: dict[str, str] = {}
    client = TestClient(_capture_prompt_app(captured))
    response = client.post(
        "/chat/preview",
        json={
            "history": [],
            "message": {"role": "user", "content": "hi"},
        },
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_build_preview_delivery_preserves_bubbles_and_delays(monkeypatch) -> None:
    from magi.api.routers.chat_preview_routes import _build_preview_delivery
    from magi.agent.response_rhythm import ResponseRhythmPlanner

    monkeypatch.setattr(
        ResponseRhythmPlanner,
        "_is_enabled",
        staticmethod(lambda: True),
    )
    result = await _build_preview_delivery("first short message‖second short message")
    assert result[0] == ("first short message", 0)
    assert result[1][0] == "second short message"
    assert 1000 <= result[1][1] <= 4000


@pytest.mark.asyncio
async def test_build_preview_delivery_strips_invalid_bubble_markers(monkeypatch) -> None:
    from magi.api.routers.chat_preview_routes import _build_preview_delivery
    from magi.agent.response_rhythm import ResponseRhythmPlanner

    monkeypatch.setattr(
        ResponseRhythmPlanner,
        "_is_enabled",
        staticmethod(lambda: True),
    )
    result = await _build_preview_delivery("one‖two‖three‖four‖five‖six‖seven")
    assert result == [("one two three four five six seven", 0)]
