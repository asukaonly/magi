"""Image Generation Tool - Generate images via LLM provider APIs."""
from __future__ import annotations

import base64
import time
import uuid
from pathlib import Path
from typing import Any, Dict

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
from ...config.models import LLMScenario
from ...core.logger import get_logger

logger = get_logger(__name__, category="TOOLS")


class ImageGenerationTool(Tool):
    """Generate images from text prompts using configured image generation models."""

    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="image-generation",
            description=(
                "Generate images from text descriptions using the configured "
                "image generation model. The model must be configured in "
                "Settings → Models → Image Generation before use.\n\n"
                "Returns the file path of the generated image."
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
            timeout=120,
            retry_on_failure=False,
            dangerous=False,
            tags=["image", "generation", "creative"],
        )

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
            from ...llm.factory import create_llm_adapter

            provider_type = str(
                getattr(
                    getattr(provider_settings, "provider_type", ""),
                    "value",
                    getattr(provider_settings, "provider_type", ""),
                )
                or "openai"
            ).strip().lower()

            if provider_type == "custom":
                api_format = str(
                    getattr(provider_settings, "api_format", "") or "openai"
                ).strip().lower()
                provider_type = api_format if api_format == "anthropic" else "openai"

            proxy_url = (
                config.network.proxy_url()
                if hasattr(config, "network")
                else None
            )

            adapter = create_llm_adapter(
                provider_type=provider_type,
                api_key=provider_settings.api_key,
                model=selection.model,
                base_url=provider_settings.base_url,
                timeout=config.llm.timeout,
                proxy_url=proxy_url,
            )

            result = await adapter.generate_image(
                prompt=prompt,
                model=selection.model,
                size=size,
                quality=quality,
                n=1,
            )

            if result is None:
                return ToolResult(
                    success=False,
                    error=(
                        f"Provider '{provider_type}' does not support image generation."
                    ),
                    error_code=ToolErrorCode.NOT_IMPLEMENTED.value,
                    execution_time=time.time() - start,
                )

            images = result.get("images", [])
            if not images:
                return ToolResult(
                    success=False,
                    error="No images were returned by the provider.",
                    error_code=ToolErrorCode.EXECUTION_ERROR.value,
                    execution_time=time.time() - start,
                )

            image_entry = images[0]
            saved_paths: list[str] = []

            workspace = Path(context.workspace).resolve()
            output_dir = workspace / "generated_images"
            output_dir.mkdir(parents=True, exist_ok=True)

            for idx, img in enumerate(images):
                b64_data = img.get("b64_json")
                if b64_data:
                    filename = f"{uuid.uuid4().hex[:12]}.png"
                    filepath = output_dir / filename
                    filepath.write_bytes(base64.b64decode(b64_data))
                    saved_paths.append(str(filepath))
                    logger.info(
                        "Image saved",
                        path=str(filepath),
                        model=selection.model,
                    )
                elif img.get("url"):
                    saved_paths.append(img["url"])

            revised_prompt = image_entry.get("revised_prompt")
            summary_parts = [
                f"Image generated successfully using model '{selection.model}'.",
            ]
            if saved_paths:
                summary_parts.append(f"Saved to: {saved_paths[0]}")
            if revised_prompt:
                summary_parts.append(f"Revised prompt: {revised_prompt}")

            return ToolResult(
                success=True,
                data={
                    "message": " ".join(summary_parts),
                    "paths": saved_paths,
                    "model": selection.model,
                    "revised_prompt": revised_prompt,
                },
                execution_time=time.time() - start,
            )

        except Exception as exc:
            logger.error("Image generation failed", error=str(exc))
            return ToolResult(
                success=False,
                error=f"Image generation failed: {exc}",
                error_code=ToolErrorCode.EXECUTION_ERROR.value,
                execution_time=time.time() - start,
            )
