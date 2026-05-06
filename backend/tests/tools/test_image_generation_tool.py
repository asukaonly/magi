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
from magi.llm.image_generation import (
    ImageArtifact,
    ImageGenRateLimitError,
    ImageGenerationCapability,
    ImageGenerationRequest,
    ImageGenerationResponse,
)
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


class _FakeIngestionService:
    def ingest_local_file(
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


def _context(tmp_path: Path) -> ToolExecutionContext:
    return ToolExecutionContext(
        agent_id="test-agent",
        workspace=str(tmp_path),
        env_vars={"session_id": "session-1", "turn_id": "turn-1"},
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

    monkeypatch.setattr(image_tool_module, "get_config", _config)
    monkeypatch.setattr(
        image_tool_module,
        "load_llm_provider_registry",
        lambda *_args, **_kwargs: LLMProviderRegistryModel(),
    )
    adapter_kwargs: dict[str, object] = {}

    def fake_create_image_generation_adapter(**kwargs):
        adapter_kwargs.update(kwargs)
        return fake_adapter

    monkeypatch.setattr(
        image_tool_module,
        "create_image_generation_adapter",
        fake_create_image_generation_adapter,
    )

    tool = ImageGenerationTool()
    tool._ingestion_service = _FakeIngestionService()

    result = await tool.execute(
        {"prompt": "draw a small desk", "size": "1024x1024", "quality": "auto"},
        _context(tmp_path),
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

    monkeypatch.setattr(image_tool_module, "get_config", _config)
    monkeypatch.setattr(
        image_tool_module,
        "load_llm_provider_registry",
        lambda *_args, **_kwargs: LLMProviderRegistryModel(),
    )
    monkeypatch.setattr(
        image_tool_module,
        "create_image_generation_adapter",
        lambda **_kwargs: fake_adapter,
    )

    tool = ImageGenerationTool()
    tool._ingestion_service = _FakeIngestionService()

    async def fake_download_image_url(*_args, **_kwargs):
        return b"downloaded-image", "image/png"

    monkeypatch.setattr(tool, "_download_image_url", fake_download_image_url)

    result = await tool.execute({"prompt": "draw a small desk"}, _context(tmp_path))

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

    monkeypatch.setattr(image_tool_module, "get_config", _config)
    monkeypatch.setattr(
        image_tool_module,
        "load_llm_provider_registry",
        lambda *_args, **_kwargs: LLMProviderRegistryModel(),
    )
    monkeypatch.setattr(
        image_tool_module,
        "create_image_generation_adapter",
        lambda **_kwargs: fake_adapter,
    )

    tool = ImageGenerationTool()
    tool._ingestion_service = _FakeIngestionService()

    result = await tool.execute({"prompt": "draw a small desk"}, _context(tmp_path))

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

    monkeypatch.setattr(image_tool_module, "get_config", lambda: stale_config)
    monkeypatch.setattr(image_tool_module, "reload_config", _config)
    monkeypatch.setattr(
        image_tool_module,
        "load_llm_provider_registry",
        lambda *_args, **_kwargs: LLMProviderRegistryModel(),
    )
    monkeypatch.setattr(
        image_tool_module,
        "create_image_generation_adapter",
        lambda **_kwargs: fake_adapter,
    )

    tool = ImageGenerationTool()
    tool._ingestion_service = _FakeIngestionService()

    result = await tool.execute({"prompt": "draw a small desk"}, _context(tmp_path))

    assert result.success is True
    assert fake_adapter.requests[0].prompt == "draw a small desk"


@pytest.mark.asyncio
async def test_image_generation_tool_maps_rate_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_adapter = _FakeAdapter(error=ImageGenRateLimitError("slow down", status_code=429))

    monkeypatch.setattr(image_tool_module, "get_config", _config)
    monkeypatch.setattr(
        image_tool_module,
        "load_llm_provider_registry",
        lambda *_args, **_kwargs: LLMProviderRegistryModel(),
    )
    monkeypatch.setattr(
        image_tool_module,
        "create_image_generation_adapter",
        lambda **_kwargs: fake_adapter,
    )

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(image_tool_module.asyncio, "sleep", no_sleep)

    tool = ImageGenerationTool()
    result = await tool.execute({"prompt": "draw a small desk"}, _context(tmp_path))

    assert result.success is False
    assert result.error_code == ToolErrorCode.RATE_LIMITED.value
    assert result.metadata["status_code"] == 429
    assert len(fake_adapter.requests) == 2
    assert fake_adapter.closed is True
