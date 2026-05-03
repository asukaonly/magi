"""Image generation adapter contracts and factory helpers."""

from .base import ImageGenerationAdapter
from .errors import (
    ImageGenAuthError,
    ImageGenContentFilteredError,
    ImageGenInvalidParameterError,
    ImageGenProviderError,
    ImageGenRateLimitError,
    ImageGenTimeoutError,
)
from .factory import create_image_generation_adapter, is_image_generation_supported
from .types import (
    ImageArtifact,
    ImageGenerationCapability,
    ImageGenerationRequest,
    ImageGenerationResponse,
)

__all__ = [
    "ImageArtifact",
    "ImageGenAuthError",
    "ImageGenContentFilteredError",
    "ImageGenInvalidParameterError",
    "ImageGenProviderError",
    "ImageGenRateLimitError",
    "ImageGenTimeoutError",
    "ImageGenerationAdapter",
    "ImageGenerationCapability",
    "ImageGenerationRequest",
    "ImageGenerationResponse",
    "create_image_generation_adapter",
    "is_image_generation_supported",
]
