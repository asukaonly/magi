"""Image Generation Tool - Generate images via LLM provider APIs."""

from __future__ import annotations

import asyncio
import base64
import binascii
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse

import httpx

from magi_plugin_sdk.image_generation import (
    MAX_IMAGE_ATTACHMENT_BYTES,
    ImageArtifact,
    ImageGenAuthError,
    ImageGenContentFilteredError,
    ImageGenInvalidParameterError,
    ImageGenProviderError,
    ImageGenRateLimitError,
    ImageGenTimeoutError,
    ImageGenerationRequest,
)
from ..schema import (
    Tool,
    ToolSchema,
    ToolExecutionContext,
    ToolResult,
    ToolParameter,
    ParameterType,
    ToolErrorCode,
)
from ...config import get_config, reload_config
from ...config.loader import get_llm_provider_registry_file
from ...config.llm_registry import LLMProviderRegistryModel, load_llm_provider_registry
from ...config.models import LLMScenario

from ...core.logger import get_logger

logger = get_logger(__name__, category="TOOLS")

DEFAULT_IMAGE_GENERATION_TIMEOUT_SECONDS = 180
DEFAULT_IMAGE_DOWNLOAD_TIMEOUT_SECONDS = 30
TRANSIENT_IMAGE_GENERATION_RETRIES = 1


@dataclass(frozen=True)
class _ImageGenerationInputs:
    prompt: str
    size: str
    quality: str


@dataclass(frozen=True)
class _ImageGenerationExecution:
    selection: Any
    image_gen: Any
    proxy_url: str | None
    adapter: Any
    request_size: str
    event_context: dict[str, Any]


@dataclass(frozen=True)
class _PersistedImageArtifact:
    saved_path: str | None
    artifact: dict[str, Any]
    chat_attachment: Any = None
    has_chat_attachment: bool = False


class ImageGenerationTool(Tool):
    """Generate images from text prompts using configured image generation models."""

    def __init__(self) -> None:
        super().__init__()

    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="image-generation",
            description=(
                "Generate images from text descriptions using the configured "
                "image generation model. The model must be configured in "
                "Settings → Models → Image Generation before use.\n\n"
                "Returns generated image metadata and chat attachment metadata."
            ),
            category="generation",
            version="1.0.0",
            author="Magi Team",
            parameters=[
                ToolParameter(
                    name="prompt",
                    type=ParameterType.STRING,
                    description="A detailed text description of the image to generate.",
                    required=True,
                ),
                ToolParameter(
                    name="size",
                    type=ParameterType.STRING,
                    description=(
                        "Image dimensions. Common values: '1024x1024' (square), "
                        "'1536x1024' (landscape), '1024x1536' (portrait)."
                    ),
                    required=False,
                    default="1024x1024",
                ),
                ToolParameter(
                    name="quality",
                    type=ParameterType.STRING,
                    description="Generation quality: 'auto', 'high', 'medium', or 'low'.",
                    required=False,
                    default="auto",
                    enum=["auto", "high", "medium", "low"],
                ),
            ],
            examples=[
                {
                    "input": {"prompt": "A serene mountain landscape at sunset"},
                    "output": "Generated image saved to workspace",
                },
            ],
            timeout=DEFAULT_IMAGE_GENERATION_TIMEOUT_SECONDS,
            retry_on_failure=False,
            dangerous=False,
            effect_replay_policy="reconcilable",
            tags=["image", "generation", "creative"],
        )

    def get_schema(self) -> ToolSchema:
        if self.schema is not None:
            self.schema.timeout = self._configured_timeout_seconds()
        assert self.schema is not None
        return self.schema

    @staticmethod
    def _configured_timeout_seconds() -> int:
        try:
            return ImageGenerationTool._timeout_seconds_from_config(get_config())
        except Exception:
            return DEFAULT_IMAGE_GENERATION_TIMEOUT_SECONDS

    @staticmethod
    def _load_execution_config():
        try:
            return reload_config()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to reload config for image generation", error=str(exc))
            return get_config()

    @staticmethod
    def _timeout_seconds_from_config(config: Any) -> int:
        selection = config.llm.selections.get(LLMScenario.IMAGE_GENERATION.value)
        provider_settings = (
            config.llm.providers.get(selection.provider_id) if selection is not None else None
        )
        image_generation = getattr(
            getattr(provider_settings, "services", None),
            "image_generation",
            None,
        )
        return max(
            1,
            int(
                getattr(
                    image_generation,
                    "timeout",
                    DEFAULT_IMAGE_GENERATION_TIMEOUT_SECONDS,
                )
                or DEFAULT_IMAGE_GENERATION_TIMEOUT_SECONDS
            ),
        )

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        """Execute image generation."""
        start = time.time()
        inputs = self._parse_inputs(parameters)
        if not inputs.prompt:
            return self._failure_result(
                start,
                error="A prompt is required to generate an image.",
                error_code=ToolErrorCode.MISSING_VALUE.value,
            )

        try:
            return await self._execute_generation(inputs, context, start)
        except ImageGenProviderError as exc:
            logger.error(
                "Image generation failed",
                error=str(exc),
                code=getattr(exc, "code", None),
            )
            return self._failure_result(
                start,
                error=str(exc),
                error_code=self._tool_error_code_for_image_error(exc),
                metadata=self._error_metadata(exc),
            )

        except Exception as exc:
            logger.error("Image generation failed", error=str(exc))
            return self._failure_result(
                start,
                error=f"Image generation failed: {exc}",
                error_code=ToolErrorCode.EXECUTION_ERROR.value,
            )

    async def _execute_generation(
        self,
        inputs: _ImageGenerationInputs,
        context: ToolExecutionContext,
        start: float,
    ) -> ToolResult:
        execution, failure = self._prepare_execution(inputs, context, start)
        if failure is not None:
            return failure
        assert execution is not None

        result = await self._generate_images(execution, inputs)
        if not result.images:
            return self._failure_result(
                start,
                error="No images were returned by the provider.",
                error_code=ToolErrorCode.EXECUTION_ERROR.value,
            )

        return await self._success_result(
            start,
            result=result,
            execution=execution,
            context=context,
        )

    @staticmethod
    def _parse_inputs(parameters: Dict[str, Any]) -> _ImageGenerationInputs:
        return _ImageGenerationInputs(
            prompt=str(parameters.get("prompt") or "").strip(),
            size=str(parameters.get("size") or "").strip(),
            quality=str(parameters.get("quality") or "auto").strip(),
        )

    def _prepare_execution(
        self,
        inputs: _ImageGenerationInputs,
        context: ToolExecutionContext,
        start: float,
    ) -> tuple[_ImageGenerationExecution | None, ToolResult | None]:
        config = self._load_execution_config()
        selection, failure = self._resolve_image_selection(config, start)
        if failure is not None:
            return None, failure
        assert selection is not None

        provider_settings, failure = self._resolve_provider_settings(config, selection, start)
        if failure is not None:
            return None, failure
        assert provider_settings is not None

        image_gen, failure = self._resolve_image_generation_capability(context, start)
        if failure is not None:
            return None, failure
        assert image_gen is not None

        proxy_url = config.network.proxy_url() if hasattr(config, "network") else None
        adapter = self._create_image_adapter(
            config=config,
            selection=selection,
            provider_settings=provider_settings,
            image_gen=image_gen,
            proxy_url=proxy_url,
        )
        return (
            _ImageGenerationExecution(
                selection=selection,
                image_gen=image_gen,
                proxy_url=proxy_url,
                adapter=adapter,
                request_size=inputs.size or self._default_size_for_adapter(adapter),
                event_context=self._event_context(context),
            ),
            None,
        )

    def _resolve_image_selection(
        self,
        config: Any,
        start: float,
    ) -> tuple[Any | None, ToolResult | None]:
        selection = config.llm.selections.get(LLMScenario.IMAGE_GENERATION.value)
        if selection is None or not selection.model:
            return None, self._failure_result(
                start,
                error=(
                    "Image generation model is not configured. "
                    "Please configure it in Settings → Models → Image Generation."
                ),
                error_code=ToolErrorCode.PROVIDER_NOT_CONFIGURED.value,
            )
        return selection, None

    def _resolve_provider_settings(
        self,
        config: Any,
        selection: Any,
        start: float,
    ) -> tuple[Any | None, ToolResult | None]:
        provider_settings = config.llm.providers.get(selection.provider_id)
        if provider_settings is None or not provider_settings.enabled:
            return None, self._failure_result(
                start,
                error=(
                    f"Provider '{selection.provider_id}' for image generation "
                    f"is not enabled or not configured."
                ),
                error_code=ToolErrorCode.PROVIDER_NOT_CONFIGURED.value,
            )

        image_generation = provider_settings.services.image_generation
        if not image_generation.enabled:
            return None, self._failure_result(
                start,
                error=f"Provider '{selection.provider_id}' does not have image generation enabled.",
                error_code=ToolErrorCode.PROVIDER_NOT_CONFIGURED.value,
            )

        if not (image_generation.api_key or provider_settings.api_key):
            return None, self._failure_result(
                start,
                error=f"Provider '{selection.provider_id}' is missing an API key.",
                error_code=ToolErrorCode.AUTH_REQUIRED.value,
            )
        return provider_settings, None

    def _resolve_image_generation_capability(
        self,
        context: ToolExecutionContext,
        start: float,
    ) -> tuple[Any | None, ToolResult | None]:
        image_gen = context.capabilities.image_gen if context.capabilities else None
        if image_gen is None:
            return None, self._failure_result(
                start,
                error="Image generation capability is not available.",
                error_code=ToolErrorCode.EXECUTION_ERROR.value,
            )
        return image_gen, None

    def _create_image_adapter(
        self,
        *,
        config: Any,
        selection: Any,
        provider_settings: Any,
        image_gen: Any,
        proxy_url: str | None,
    ) -> Any:
        registry = load_llm_provider_registry(
            get_llm_provider_registry_file(),
            fallback=LLMProviderRegistryModel(),
        )
        return image_gen.create_adapter(
            provider_id=selection.provider_id,
            provider_settings=provider_settings,
            model=selection.model,
            registry=registry,
            timeout=self._timeout_seconds_from_config(config),
            proxy_url=proxy_url,
        )

    async def _generate_images(
        self,
        execution: _ImageGenerationExecution,
        inputs: _ImageGenerationInputs,
    ):
        try:
            return await self._generate_with_transient_retry(
                execution.adapter,
                ImageGenerationRequest(
                    prompt=inputs.prompt,
                    model=execution.selection.model,
                    size=execution.request_size,
                    quality=inputs.quality,
                    n=1,
                ),
                image_gen=execution.image_gen,
                event_context=execution.event_context,
            )
        finally:
            await self._close_adapter(execution.adapter)

    async def _success_result(
        self,
        start: float,
        *,
        result,
        execution: _ImageGenerationExecution,
        context: ToolExecutionContext,
    ) -> ToolResult:
        chat_port = context.capabilities.chat if context.capabilities else None
        saved_paths, artifacts, chat_attachments = await self._persist_images(
            images=result.images,
            workspace=Path(context.workspace).resolve(),
            model=execution.selection.model,
            session_id=str(context.env_vars.get("session_id") or "").strip(),
            turn_id=str(context.env_vars.get("turn_id") or "").strip(),
            proxy_url=execution.proxy_url,
            chat_port=chat_port,
        )
        revised_prompt = self._first_revised_prompt(artifacts)
        summary = self._success_summary(
            model=str(result.model),
            saved_paths=saved_paths,
            artifacts=artifacts,
            chat_attachments=chat_attachments,
            revised_prompt=revised_prompt,
        )
        data = self._success_data(
            summary=summary,
            saved_paths=saved_paths,
            model=str(result.model),
            artifacts=artifacts,
            chat_attachments=chat_attachments,
            revised_prompt=revised_prompt,
        )
        return ToolResult(
            success=True,
            data=data,
            execution_time=time.time() - start,
        )

    @staticmethod
    def _event_context(context: ToolExecutionContext) -> dict[str, Any]:
        return {
            "agent_id": "image_generation_tool",
            "session_id": str(context.env_vars.get("session_id") or "").strip() or None,
            "turn_id": str(context.env_vars.get("turn_id") or "").strip() or None,
        }

    @staticmethod
    def _first_revised_prompt(artifacts: list[dict[str, Any]]) -> Any:
        return next(
            (
                artifact.get("revised_prompt")
                for artifact in artifacts
                if artifact.get("revised_prompt")
            ),
            None,
        )

    @staticmethod
    def _success_summary(
        *,
        model: str,
        saved_paths: list[str],
        artifacts: list[dict[str, Any]],
        chat_attachments: list[dict[str, object]],
        revised_prompt: Any,
    ) -> str:
        summary_parts = [
            f"Generated {len(artifacts)} image(s) using model '{model}'.",
        ]
        if chat_attachments:
            summary_parts.append(
                f"Attached {len(chat_attachments)} generated image(s) to the reply."
            )
        elif saved_paths:
            summary_parts.append(f"Saved to: {saved_paths[0]}")
        if revised_prompt:
            summary_parts.append(f"Revised prompt: {revised_prompt}")
        return " ".join(summary_parts)

    def _success_data(
        self,
        *,
        summary: str,
        saved_paths: list[str],
        model: str,
        artifacts: list[dict[str, Any]],
        chat_attachments: list[dict[str, object]],
        revised_prompt: Any,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "summary": summary,
            "message": summary,
            "paths": saved_paths,
            "model": model,
            "artifacts": artifacts,
            "chat_attachments": chat_attachments,
        }
        if revised_prompt:
            data["revised_prompt"] = revised_prompt
        asset_refs = self._build_attachment_asset_refs(chat_attachments)
        if asset_refs:
            data["assistant_payload"] = {"asset_refs": asset_refs}
        return data

    @staticmethod
    def _failure_result(
        start: float,
        *,
        error: str,
        error_code: str,
        metadata: dict[str, Any] | None = None,
    ) -> ToolResult:
        return ToolResult(
            success=False,
            error=error,
            error_code=error_code,
            execution_time=time.time() - start,
            metadata=metadata,
        )

    async def _generate_with_transient_retry(
        self,
        adapter,
        request: ImageGenerationRequest,
        *,
        image_gen,
        event_context: dict[str, Any] | None = None,
    ):
        started_at = time.time()
        last_error: ImageGenProviderError | None = None
        try:
            for attempt in range(TRANSIENT_IMAGE_GENERATION_RETRIES + 1):
                try:
                    result = await adapter.generate(request)
                    generated_count = (
                        len(result.images)
                        if getattr(result, "images", None)
                        else int(getattr(request, "n", 0) or 0)
                    )
                    await self._publish_image_generation_usage(
                        adapter,
                        request=request,
                        started_at=started_at,
                        success=True,
                        image_gen=image_gen,
                        event_context=event_context,
                        resolved_model=result.model,
                        image_count=generated_count,
                    )
                    return result
                except (ImageGenRateLimitError, ImageGenTimeoutError) as exc:
                    last_error = exc
                    if attempt >= TRANSIENT_IMAGE_GENERATION_RETRIES:
                        raise
                    await asyncio.sleep(1.0 * (attempt + 1))
            assert last_error is not None
            raise last_error
        except Exception as exc:
            await self._publish_image_generation_usage(
                adapter,
                request=request,
                started_at=started_at,
                success=False,
                error=str(exc),
                image_gen=image_gen,
                event_context=event_context,
            )
            raise

    async def _publish_image_generation_usage(
        self,
        adapter,
        *,
        request: ImageGenerationRequest,
        started_at: float,
        success: bool,
        image_gen,
        error: str | None = None,
        event_context: dict[str, Any] | None = None,
        resolved_model: str | None = None,
        image_count: int = 0,
    ) -> None:
        if image_gen is None:
            return
        try:
            await image_gen.publish_usage_span(
                provider=str(getattr(adapter, "provider_id", "unknown") or "unknown"),
                model=str(
                    resolved_model
                    or request.model
                    or getattr(adapter, "_model", "image_generation")
                ),
                request_kind="image_generation",
                success=success,
                started_at=started_at,
                image_count=int(image_count or 0),
                usage_available=bool(success and image_count),
                error=error,
                event_context=event_context,
            )
        except Exception:
            logger.debug("Image generation usage publication failed", exc_info=True)

    @staticmethod
    def _default_size_for_adapter(adapter: Any) -> str:
        capability = getattr(adapter, "capability", None)
        supported_sizes = getattr(capability, "supported_sizes", None)
        if isinstance(supported_sizes, list) and supported_sizes:
            return str(supported_sizes[0])
        return "1024x1024"

    @staticmethod
    async def _close_adapter(adapter: Any) -> None:
        try:
            await adapter.aclose()
        except Exception as exc:  # noqa: BLE001 - cleanup must not hide generation errors
            logger.warning("Image generation adapter cleanup failed", error=str(exc))

    async def _persist_images(
        self,
        *,
        images: list[ImageArtifact],
        workspace: Path,
        model: str,
        session_id: str,
        turn_id: str,
        proxy_url: str | None = None,
        chat_port,
    ) -> tuple[list[str], list[dict[str, Any]], list[dict[str, object]]]:
        output_dir = workspace / "generated_images"
        output_dir.mkdir(parents=True, exist_ok=True)
        saved_paths: list[str] = []
        artifacts: list[dict[str, Any]] = []
        chat_attachments: list[dict[str, object]] = []

        for idx, image in enumerate(images):
            persisted = await self._persist_image_artifact(
                idx=idx,
                image=image,
                output_dir=output_dir,
                model=model,
                session_id=session_id,
                turn_id=turn_id,
                proxy_url=proxy_url,
                chat_port=chat_port,
            )
            if persisted.saved_path is not None:
                saved_paths.append(persisted.saved_path)
            if persisted.has_chat_attachment:
                chat_attachments.append(persisted.chat_attachment)
            artifacts.append(persisted.artifact)

        return saved_paths, artifacts, chat_attachments

    async def _persist_image_artifact(
        self,
        *,
        idx: int,
        image: ImageArtifact,
        output_dir: Path,
        model: str,
        session_id: str,
        turn_id: str,
        proxy_url: str | None,
        chat_port: Any,
    ) -> _PersistedImageArtifact:
        image_bytes, image_mime = await self._image_bytes_and_mime(image, proxy_url=proxy_url)
        saved_path: str | None = None
        chat_attachment = None
        has_chat_attachment = False
        if image_bytes is not None:
            saved_path = await asyncio.to_thread(
                self._write_generated_image,
                image_bytes=image_bytes,
                image_mime=image_mime,
                output_dir=output_dir,
                model=model,
            )
            if session_id and turn_id and chat_port is not None:
                chat_attachment = await chat_port.ingest_local_file(
                    session_id=session_id,
                    turn_id=turn_id,
                    file_path=saved_path,
                    original_name=Path(saved_path).name,
                    mime_type=image_mime,
                )
                has_chat_attachment = True
        elif image.url:
            saved_path = image.url

        return _PersistedImageArtifact(
            saved_path=saved_path,
            artifact=self._image_artifact_payload(
                idx=idx,
                image=image,
                image_mime=image_mime,
                saved_path=saved_path,
                attachment=chat_attachment,
            ),
            chat_attachment=chat_attachment,
            has_chat_attachment=has_chat_attachment,
        )

    async def _image_bytes_and_mime(
        self,
        image: ImageArtifact,
        *,
        proxy_url: str | None,
    ) -> tuple[bytes | None, str]:
        if image.b64:
            return self._decode_image_b64(image.b64), image.mime
        if not image.url:
            return None, image.mime
        downloaded = await self._download_image_url(
            image.url,
            fallback_mime=image.mime,
            proxy_url=proxy_url,
        )
        if downloaded is None:
            return None, image.mime
        return downloaded

    def _write_generated_image(
        self,
        *,
        image_bytes: bytes,
        image_mime: str,
        output_dir: Path,
        model: str,
    ) -> str:
        extension = self._extension_for_mime(image_mime)
        filename = f"{uuid.uuid4().hex[:12]}{extension}"
        filepath = output_dir / filename
        filepath.write_bytes(image_bytes)
        saved_path = str(filepath)
        logger.info("Image saved", path=saved_path, model=model)
        return saved_path

    @staticmethod
    def _image_artifact_payload(
        *,
        idx: int,
        image: ImageArtifact,
        image_mime: str,
        saved_path: str | None,
        attachment: Any,
    ) -> dict[str, Any]:
        artifact_payload: dict[str, Any] = {
            "index": idx,
            "mime": image_mime,
            "path": saved_path,
            "url": image.url,
            "seed": image.seed,
            "revised_prompt": image.revised_prompt,
        }
        if attachment is not None:
            artifact_payload["attachment_id"] = attachment.get("attachment_id")
        return {key: value for key, value in artifact_payload.items() if value is not None}

    @staticmethod
    def _decode_image_b64(value: str) -> bytes:
        try:
            return base64.b64decode(value, validate=True)
        except binascii.Error as exc:
            raise ImageGenInvalidParameterError(
                "Provider returned invalid base64 image data.",
                field="image.b64",
                raw=exc,
            ) from exc

    @staticmethod
    async def _download_image_url(
        url: str,
        *,
        fallback_mime: str,
        proxy_url: str | None = None,
    ) -> tuple[bytes, str] | None:
        parsed = urlparse(str(url or "").strip())
        if parsed.scheme not in {"http", "https"}:
            logger.warning("Skipping generated image URL with unsupported scheme", url=url)
            return None

        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                proxy=proxy_url,
                timeout=DEFAULT_IMAGE_DOWNLOAD_TIMEOUT_SECONDS,
                trust_env=False,
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
                content_type = (
                    str(response.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
                )
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > MAX_IMAGE_ATTACHMENT_BYTES:
                    logger.warning("Generated image URL is too large to import", url=url)
                    return None
                content = await response.aread()
        except Exception as exc:  # noqa: BLE001 - provider URLs are best-effort artifact imports
            logger.warning("Failed to download generated image URL", url=url, error=str(exc))
            return None

        if not content or len(content) > MAX_IMAGE_ATTACHMENT_BYTES:
            logger.warning("Generated image URL content is empty or too large", url=url)
            return None
        if (
            content_type
            and not content_type.startswith("image/")
            and content_type != "application/octet-stream"
        ):
            logger.warning(
                "Generated image URL returned a non-image content type",
                url=url,
                content_type=content_type,
            )
            return None
        resolved_mime = content_type if content_type.startswith("image/") else fallback_mime
        return content, resolved_mime or "image/png"

    @staticmethod
    def _extension_for_mime(mime: str) -> str:
        normalized = str(mime or "").strip().lower()
        if normalized == "image/jpeg":
            return ".jpg"
        if normalized == "image/webp":
            return ".webp"
        return ".png"

    @staticmethod
    def _build_attachment_asset_refs(
        attachments: list[dict[str, object]],
    ) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        for attachment in attachments:
            attachment_id = str(attachment.get("attachment_id") or "").strip()
            if not attachment_id:
                continue
            refs.append(
                {
                    "asset_ref_id": f"chat_attachment:{attachment_id}",
                    "attachment_id": attachment_id,
                    "source_type": "chat_attachment",
                    "kind": attachment.get("kind") or "image",
                    "original_name": attachment.get("original_name"),
                    "display_name": attachment.get("original_name"),
                    "resolution_state": "resolved",
                }
            )
        return refs

    @staticmethod
    def _tool_error_code_for_image_error(exc: ImageGenProviderError) -> str:
        if isinstance(exc, ImageGenAuthError):
            return ToolErrorCode.AUTH_REQUIRED.value
        if isinstance(exc, ImageGenRateLimitError):
            return ToolErrorCode.RATE_LIMITED.value
        if isinstance(exc, ImageGenContentFilteredError):
            return ToolErrorCode.POLICY_BLOCKED.value
        if isinstance(exc, ImageGenInvalidParameterError):
            return ToolErrorCode.INVALID_PARAMETERS.value
        if isinstance(exc, ImageGenTimeoutError):
            return ToolErrorCode.TIMEOUT.value
        return ToolErrorCode.EXECUTION_ERROR.value

    @staticmethod
    def _error_metadata(exc: ImageGenProviderError) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        if exc.status_code is not None:
            metadata["status_code"] = exc.status_code
        if exc.code:
            metadata["provider_code"] = exc.code
        if isinstance(exc, ImageGenInvalidParameterError):
            if exc.field:
                metadata["field"] = exc.field
            if exc.allowed_values:
                metadata["allowed_values"] = exc.allowed_values
        return metadata
