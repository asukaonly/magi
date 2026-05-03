"""Image Generation Tool - Generate images via LLM provider APIs."""

from __future__ import annotations

import asyncio
import base64
import time
import uuid
from pathlib import Path
from typing import Any, Dict

from ...chat.attachment_ingestion import LocalChatAttachmentIngestionService
from ..schema import (
    Tool,
    ToolSchema,
    ToolExecutionContext,
    ToolResult,
    ToolParameter,
    ParameterType,
    ToolErrorCode,
)
from ...config import get_config
from ...config.loader import get_llm_provider_registry_file
from ...config.llm_registry import LLMProviderRegistryModel, load_llm_provider_registry
from ...config.models import LLMScenario
from ...core.logger import get_logger
from ...llm.image_generation import (
    ImageArtifact,
    ImageGenAuthError,
    ImageGenContentFilteredError,
    ImageGenInvalidParameterError,
    ImageGenProviderError,
    ImageGenRateLimitError,
    ImageGenTimeoutError,
    ImageGenerationRequest,
    create_image_generation_adapter,
)

logger = get_logger(__name__, category="TOOLS")

DEFAULT_IMAGE_GENERATION_TIMEOUT_SECONDS = 180
TRANSIENT_IMAGE_GENERATION_RETRIES = 1


class ImageGenerationTool(Tool):
    """Generate images from text prompts using configured image generation models."""

    def __init__(self) -> None:
        self._ingestion_service = LocalChatAttachmentIngestionService()
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
            config = get_config()
            return max(
                1,
                int(
                    getattr(
                        config.llm,
                        "image_generation_timeout",
                        DEFAULT_IMAGE_GENERATION_TIMEOUT_SECONDS,
                    )
                    or DEFAULT_IMAGE_GENERATION_TIMEOUT_SECONDS
                ),
            )
        except Exception:
            return DEFAULT_IMAGE_GENERATION_TIMEOUT_SECONDS

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        """Execute image generation."""
        start = time.time()
        prompt = str(parameters.get("prompt") or "").strip()
        if not prompt:
            return ToolResult(
                success=False,
                error="A prompt is required to generate an image.",
                error_code=ToolErrorCode.MISSING_VALUE.value,
                execution_time=time.time() - start,
            )

        size = str(parameters.get("size") or "1024x1024").strip()
        quality = str(parameters.get("quality") or "auto").strip()

        config = get_config()
        selection = config.llm.selections.get(LLMScenario.IMAGE_GENERATION.value)
        if selection is None or not selection.model:
            return ToolResult(
                success=False,
                error=(
                    "Image generation model is not configured. "
                    "Please configure it in Settings → Models → Image Generation."
                ),
                error_code=ToolErrorCode.PROVIDER_NOT_CONFIGURED.value,
                execution_time=time.time() - start,
            )

        provider_settings = config.llm.providers.get(selection.provider_id)
        if provider_settings is None or not provider_settings.enabled:
            return ToolResult(
                success=False,
                error=(
                    f"Provider '{selection.provider_id}' for image generation "
                    f"is not enabled or not configured."
                ),
                error_code=ToolErrorCode.PROVIDER_NOT_CONFIGURED.value,
                execution_time=time.time() - start,
            )

        if not provider_settings.api_key:
            return ToolResult(
                success=False,
                error=f"Provider '{selection.provider_id}' is missing an API key.",
                error_code=ToolErrorCode.AUTH_REQUIRED.value,
                execution_time=time.time() - start,
            )

        try:
            proxy_url = config.network.proxy_url() if hasattr(config, "network") else None
            registry = load_llm_provider_registry(
                get_llm_provider_registry_file(),
                fallback=LLMProviderRegistryModel(),
            )
            adapter = create_image_generation_adapter(
                provider_id=selection.provider_id,
                provider_settings=provider_settings,
                model=selection.model,
                registry=registry,
                timeout=self._configured_timeout_seconds(),
                proxy_url=proxy_url,
            )

            result = await self._generate_with_transient_retry(
                adapter,
                ImageGenerationRequest(
                    prompt=prompt,
                    model=selection.model,
                    size=size,
                    quality=quality,
                    n=1,
                ),
            )

            if not result.images:
                return ToolResult(
                    success=False,
                    error="No images were returned by the provider.",
                    error_code=ToolErrorCode.EXECUTION_ERROR.value,
                    execution_time=time.time() - start,
                )

            saved_paths, artifacts, chat_attachments = self._persist_images(
                images=result.images,
                workspace=Path(context.workspace).resolve(),
                model=selection.model,
                session_id=str(context.env_vars.get("session_id") or "").strip(),
                turn_id=str(context.env_vars.get("turn_id") or "").strip(),
            )

            revised_prompt = next(
                (
                    artifact.get("revised_prompt")
                    for artifact in artifacts
                    if artifact.get("revised_prompt")
                ),
                None,
            )
            summary_parts = [
                f"Generated {len(artifacts)} image(s) using model '{result.model}'.",
            ]
            if saved_paths:
                summary_parts.append(f"Saved to: {saved_paths[0]}")
            if chat_attachments:
                summary_parts.append(f"Prepared {len(chat_attachments)} chat attachment(s).")
            if revised_prompt:
                summary_parts.append(f"Revised prompt: {revised_prompt}")

            asset_refs = self._build_attachment_asset_refs(chat_attachments)
            data: dict[str, Any] = {
                "summary": " ".join(summary_parts),
                "message": " ".join(summary_parts),
                "paths": saved_paths,
                "model": result.model,
                "artifacts": artifacts,
                "chat_attachments": chat_attachments,
            }
            if revised_prompt:
                data["revised_prompt"] = revised_prompt
            if asset_refs:
                data["assistant_payload"] = {"asset_refs": asset_refs}

            return ToolResult(
                success=True,
                data=data,
                execution_time=time.time() - start,
            )

        except ImageGenProviderError as exc:
            logger.error(
                "Image generation failed",
                error=str(exc),
                code=getattr(exc, "code", None),
            )
            return ToolResult(
                success=False,
                error=str(exc),
                error_code=self._tool_error_code_for_image_error(exc),
                execution_time=time.time() - start,
                metadata=self._error_metadata(exc),
            )

        except Exception as exc:
            logger.error("Image generation failed", error=str(exc))
            return ToolResult(
                success=False,
                error=f"Image generation failed: {exc}",
                error_code=ToolErrorCode.EXECUTION_ERROR.value,
                execution_time=time.time() - start,
            )

    async def _generate_with_transient_retry(
        self,
        adapter,
        request: ImageGenerationRequest,
    ):
        last_error: ImageGenProviderError | None = None
        for attempt in range(TRANSIENT_IMAGE_GENERATION_RETRIES + 1):
            try:
                return await adapter.generate(request)
            except (ImageGenRateLimitError, ImageGenTimeoutError) as exc:
                last_error = exc
                if attempt >= TRANSIENT_IMAGE_GENERATION_RETRIES:
                    raise
                await asyncio.sleep(1.0 * (attempt + 1))
        assert last_error is not None
        raise last_error

    def _persist_images(
        self,
        *,
        images: list[ImageArtifact],
        workspace: Path,
        model: str,
        session_id: str,
        turn_id: str,
    ) -> tuple[list[str], list[dict[str, Any]], list[dict[str, object]]]:
        output_dir = workspace / "generated_images"
        output_dir.mkdir(parents=True, exist_ok=True)

        saved_paths: list[str] = []
        artifacts: list[dict[str, Any]] = []
        chat_attachments: list[dict[str, object]] = []

        for idx, image in enumerate(images):
            saved_path: str | None = None
            attachment: dict[str, object] | None = None

            if image.b64:
                extension = self._extension_for_mime(image.mime)
                filename = f"{uuid.uuid4().hex[:12]}{extension}"
                filepath = output_dir / filename
                filepath.write_bytes(base64.b64decode(image.b64))
                saved_path = str(filepath)
                saved_paths.append(saved_path)
                logger.info("Image saved", path=saved_path, model=model)
                if session_id and turn_id:
                    attachment = self._ingestion_service.ingest_local_file(
                        session_id=session_id,
                        turn_id=turn_id,
                        file_path=saved_path,
                        original_name=filename,
                        mime_type=image.mime,
                    )
                    chat_attachments.append(attachment)
            elif image.url:
                saved_path = image.url
                saved_paths.append(image.url)

            artifact_payload: dict[str, Any] = {
                "index": idx,
                "mime": image.mime,
                "path": saved_path,
                "url": image.url,
                "seed": image.seed,
                "revised_prompt": image.revised_prompt,
            }
            if attachment is not None:
                artifact_payload["attachment_id"] = attachment.get("attachment_id")
            artifacts.append(
                {key: value for key, value in artifact_payload.items() if value is not None}
            )

        return saved_paths, artifacts, chat_attachments

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
