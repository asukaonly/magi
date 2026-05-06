"""Base adapter contract for provider-native image generation."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .errors import ImageGenInvalidParameterError
from .types import (
    ImageGenerationCapability,
    ImageGenerationRequest,
    ImageGenerationResponse,
)


class ImageGenerationAdapter(ABC):
    """Abstract provider adapter for image generation."""

    provider_id: str
    capability: ImageGenerationCapability

    @abstractmethod
    async def generate(self, req: ImageGenerationRequest) -> ImageGenerationResponse:
        """Generate images from a provider-independent request."""

    async def aclose(self) -> None:
        """Release provider adapter resources."""

    def normalize_size(self, raw: str) -> str:
        value = str(raw or "").strip().lower()
        allowed = [
            str(item).strip().lower() for item in self.capability.supported_sizes
        ]
        if not allowed or value in allowed:
            return value
        raise ImageGenInvalidParameterError(
            f"Unsupported image size '{raw}'. Allowed values: {', '.join(self.capability.supported_sizes)}.",
            field="size",
            allowed_values=list(self.capability.supported_sizes),
            provider_id=self.provider_id,
        )

    def normalize_quality(self, raw: str) -> str:
        value = str(raw or "auto").strip().lower()
        allowed = [
            str(item).strip().lower() for item in self.capability.supported_qualities
        ]
        if not allowed or value in allowed:
            return value
        raise ImageGenInvalidParameterError(
            f"Unsupported image quality '{raw}'. Allowed values: {', '.join(self.capability.supported_qualities)}.",
            field="quality",
            allowed_values=list(self.capability.supported_qualities),
            provider_id=self.provider_id,
        )

    def validate_request(self, req: ImageGenerationRequest) -> None:
        if not req.prompt.strip():
            raise ImageGenInvalidParameterError(
                "A prompt is required to generate an image.",
                field="prompt",
                provider_id=self.provider_id,
            )
        if req.n < 1 or req.n > self.capability.max_n:
            raise ImageGenInvalidParameterError(
                f"Unsupported image count '{req.n}'. Allowed range: 1-{self.capability.max_n}.",
                field="n",
                allowed_values=[
                    str(value) for value in range(1, self.capability.max_n + 1)
                ],
                provider_id=self.provider_id,
            )
        if req.seed is not None and not self.capability.supports_seed:
            raise ImageGenInvalidParameterError(
                "The selected image generation model does not support seed.",
                field="seed",
                provider_id=self.provider_id,
            )
        if req.negative_prompt and not self.capability.supports_negative_prompt:
            raise ImageGenInvalidParameterError(
                "The selected image generation model does not support negative_prompt.",
                field="negative_prompt",
                provider_id=self.provider_id,
            )
        if req.reference_images and not self.capability.supports_reference:
            raise ImageGenInvalidParameterError(
                "The selected image generation model does not support reference images.",
                field="reference_images",
                provider_id=self.provider_id,
            )
