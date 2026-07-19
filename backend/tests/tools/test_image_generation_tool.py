"""Tests for the builtin image generation tool."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from magi.config.llm_registry_models import LLMProviderRegistryModel
from magi.config.models import (
    AppConfig,
    LLMProvider,
    LLMProviderSettings,
    LLMScenario,
    LLMSelectionSettings,
)
from magi_plugin_sdk.image_generation import (
    ImageArtifact,
    ImageGenRateLimitError,
    ImageGenerationCapability,
    ImageGenerationRequest,
    ImageGenerationResponse,
)
from magi_plugin_sdk.capabilities import ToolCapabilities
import magi.tools.builtin.image_generation_tool as image_tool_module
from magi.tools.builtin.image_generation_tool import ImageGenerationTool
from magi.tools.schema import ToolErrorCode, ToolExecutionContext


class _FakeAdapter:
    def __init__(
        self,
        response: ImageGenerationResponse | None = None,
        error: Exception | None = None,
        capability: ImageGenerationCapability | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.capability = capability
        self.requests: list[ImageGenerationRequest] = []
        self.closed = False

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response

    async def aclose(self) -> None:
        self.closed = True


class _FakeChatPort:
    async def ingest_local_file(
        self,
        *,
        session_id: str,
        turn_id: str,
        file_path: str,
        original_name: str | None = None,
        mime_type: str | None = None,
    ) -> dict[str, object]:
        assert session_id == "session-1"
        assert turn_id == "turn-1"
        assert Path(file_path).is_file()
        return {
            "attachment_id": "attachment-1",
            "kind": "image",
            "original_name": original_name or "generated.png",
            "mime_type": mime_type or "image/png",
            "size_bytes": Path(file_path).stat().st_size,
        }

    def get_attachment_payload(self, user_id, session_id, attachment_id):
        return None

    async def prepare_runtime_attachment(self, *, session_id, turn_id, attachment):
        return attachment


class _FakeImageGenPort:
    def __init__(self, fake_adapter: _FakeAdapter, *, capture: dict | None = None) -> None:
        self._adapter = fake_adapter
        self._capture = capture if capture is not None else {}
        self.usage_spans: list[dict] = []

    def create_adapter(self, *, provider_id, provider_settings, model, registry, timeout, proxy_url=None):
        self._capture.update({"provider_id": provider_id, "model": model, "timeout": timeout})
        return self._adapter

    async def publish_usage_span(self, **kwargs) -> None:
        self.usage_spans.append(kwargs)


def _config() -> AppConfig:
    config = AppConfig()
    config.llm.providers = {
        "openai": LLMProviderSettings(
            enabled=True,
            provider_type=LLMProvider.OPENAI,
            display_name="OpenAI",
        )
    }
    image_service = config.llm.providers["openai"].services.image_generation
    image_service.enabled = True
    image_service.api_key = "test-key"
    image_service.base_url = "https://api.openai.com/v1"
    image_service.timeout = 181
    config.llm.selections[LLMScenario.IMAGE_GENERATION.value] = LLMSelectionSettings(
        provider_id="openai",
        model="gpt-image-1",
    )
    return config


def _context(tmp_path: Path, *, capabilities: ToolCapabilities | None = None) -> ToolExecutionContext:
    return ToolExecutionContext(
        agent_id="test-agent",
        workspace=str(tmp_path),
        env_vars={"session_id": "session-1", "turn_id": "turn-1"},
        capabilities=capabilities,
    )


@pytest.fixture(autouse=True)
def _reload_config_uses_test_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(image_tool_module, "reload_config", _config)


@pytest.mark.asyncio
async def test_image_generation_tool_saves_and_returns_chat_attachment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    image_data = base64.b64encode(b"fake-image").decode("ascii")
    fake_adapter = _FakeAdapter(
        response=ImageGenerationResponse(
            images=[ImageArtifact(b64=image_data, revised_prompt="a better prompt")],
            model="gpt-image-1",
        )
    )
    adapter_kwargs: dict = {}
    fake_image_gen = _FakeImageGenPort(fake_adapter, capture=adapter_kwargs)
    fake_chat = _FakeChatPort()
    caps = ToolCapabilities(chat=fake_chat, image_gen=fake_image_gen)

    monkeypatch.setattr(image_tool_module, "get_config", _config)
    monkeypatch.setattr(
        image_tool_module,
        "load_llm_provider_registry",
        lambda *_args, **_kwargs: LLMProviderRegistryModel(),
    )

    tool = ImageGenerationTool()

    result = await tool.execute(
        {"prompt": "draw a small desk", "size": "1024x1024", "quality": "auto"},
        _context(tmp_path, capabilities=caps),
    )

    assert result.success is True
    assert result.data["model"] == "gpt-image-1"
    assert len(result.data["paths"]) == 1
    assert Path(result.data["paths"][0]).is_file()
    assert result.data["artifacts"][0]["attachment_id"] == "attachment-1"
    assert result.data["chat_attachments"][0]["attachment_id"] == "attachment-1"
    assert result.data["assistant_payload"]["asset_refs"][0]["attachment_id"] == "attachment-1"
    assert "Attached 1 generated image(s) to the reply." in result.data["summary"]
    assert "Saved to:" not in result.data["summary"]
    assert fake_adapter.requests[0].prompt == "draw a small desk"
    assert fake_adapter.closed is True
    assert adapter_kwargs["timeout"] == 181
    # Success publishes a usage span carrying the number of generated images,
    # which the usage subscriber prices per image.
    assert fake_image_gen.usage_spans, "expected a usage span to be published"
    span = fake_image_gen.usage_spans[-1]
    assert span["success"] is True
    assert span["request_kind"] == "image_generation"
    assert span["image_count"] == 1


@pytest.mark.asyncio
async def test_image_generation_tool_downloads_url_artifacts_as_chat_attachments(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_adapter = _FakeAdapter(
        response=ImageGenerationResponse(
            images=[ImageArtifact(url="https://images.example.com/generated.png")],
            model="gpt-image-1",
        )
    )
    fake_image_gen = _FakeImageGenPort(fake_adapter)
    fake_chat = _FakeChatPort()
    caps = ToolCapabilities(chat=fake_chat, image_gen=fake_image_gen)

    monkeypatch.setattr(image_tool_module, "get_config", _config)
    monkeypatch.setattr(
        image_tool_module,
        "load_llm_provider_registry",
        lambda *_args, **_kwargs: LLMProviderRegistryModel(),
    )

    tool = ImageGenerationTool()

    async def fake_download_image_url(*_args, **_kwargs):
        return b"downloaded-image", "image/png"

    monkeypatch.setattr(tool, "_download_image_url", fake_download_image_url)

    result = await tool.execute({"prompt": "draw a small desk"}, _context(tmp_path, capabilities=caps))

    assert result.success is True
    assert Path(result.data["paths"][0]).is_file()
    assert result.data["artifacts"][0]["url"] == "https://images.example.com/generated.png"
    assert result.data["artifacts"][0]["attachment_id"] == "attachment-1"
    assert result.data["chat_attachments"][0]["attachment_id"] == "attachment-1"
    assert fake_adapter.closed is True


@pytest.mark.asyncio
async def test_image_generation_tool_uses_model_default_size_when_size_is_omitted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_adapter = _FakeAdapter(
        response=ImageGenerationResponse(images=[ImageArtifact(b64="ZmFrZQ==")], model="glm-image"),
        capability=ImageGenerationCapability(supported_sizes=["1280x1280", "1568x1056"]),
    )
    fake_image_gen = _FakeImageGenPort(fake_adapter)
    fake_chat = _FakeChatPort()
    caps = ToolCapabilities(chat=fake_chat, image_gen=fake_image_gen)

    monkeypatch.setattr(image_tool_module, "get_config", _config)
    monkeypatch.setattr(
        image_tool_module,
        "load_llm_provider_registry",
        lambda *_args, **_kwargs: LLMProviderRegistryModel(),
    )

    tool = ImageGenerationTool()

    result = await tool.execute({"prompt": "draw a small desk"}, _context(tmp_path, capabilities=caps))

    assert result.success is True
    assert fake_adapter.requests[0].size == "1280x1280"


@pytest.mark.asyncio
async def test_image_generation_tool_reloads_config_before_execution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stale_config = _config()
    stale_config.llm.providers["openai"].services.image_generation.enabled = False
    fake_adapter = _FakeAdapter(
        response=ImageGenerationResponse(images=[ImageArtifact(b64="ZmFrZQ==")], model="gpt-image-1")
    )
    fake_image_gen = _FakeImageGenPort(fake_adapter)
    fake_chat = _FakeChatPort()
    caps = ToolCapabilities(chat=fake_chat, image_gen=fake_image_gen)

    monkeypatch.setattr(image_tool_module, "get_config", lambda: stale_config)
    monkeypatch.setattr(image_tool_module, "reload_config", _config)
    monkeypatch.setattr(
        image_tool_module,
        "load_llm_provider_registry",
        lambda *_args, **_kwargs: LLMProviderRegistryModel(),
    )

    tool = ImageGenerationTool()

    result = await tool.execute({"prompt": "draw a small desk"}, _context(tmp_path, capabilities=caps))

    assert result.success is True
    assert fake_adapter.requests[0].prompt == "draw a small desk"


@pytest.mark.asyncio
async def test_image_generation_tool_maps_rate_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_adapter = _FakeAdapter(error=ImageGenRateLimitError("slow down", status_code=429))
    fake_image_gen = _FakeImageGenPort(fake_adapter)
    caps = ToolCapabilities(image_gen=fake_image_gen)

    monkeypatch.setattr(image_tool_module, "get_config", _config)
    monkeypatch.setattr(
        image_tool_module,
        "load_llm_provider_registry",
        lambda *_args, **_kwargs: LLMProviderRegistryModel(),
    )

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(image_tool_module.asyncio, "sleep", no_sleep)

    tool = ImageGenerationTool()
    result = await tool.execute({"prompt": "draw a small desk"}, _context(tmp_path, capabilities=caps))

    assert result.success is False
    assert result.error_code == ToolErrorCode.RATE_LIMITED.value
    assert result.metadata["status_code"] == 429
    assert len(fake_adapter.requests) == 2
    assert fake_adapter.closed is True
