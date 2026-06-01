"""Image generation contract types promoted to the SDK.

Pure types only — no host imports. Plugins and tools import from here.
The host magi.llm.image_generation.{types,errors,base} modules re-export
from this package to preserve class identity.
"""

from __future__ import annotations

from .errors import (
    ImageGenAuthError,
    ImageGenContentFilteredError,
    ImageGenInvalidParameterError,
    ImageGenProviderError,
    ImageGenRateLimitError,
    ImageGenTimeoutError,
)
from .types import (
    ImageArtifact,
    ImageGenerationCapability,
    ImageGenerationRequest,
    ImageGenerationResponse,
)

# Constant promoted alongside the types so tools can import it from the SDK
# without touching host chat internals.
MAX_IMAGE_ATTACHMENT_BYTES = 20 * 1024 * 1024

__all__ = [
    "ImageArtifact",
    "ImageGenAuthError",
    "ImageGenContentFilteredError",
    "ImageGenInvalidParameterError",
    "ImageGenProviderError",
    "ImageGenRateLimitError",
    "ImageGenTimeoutError",
    "ImageGenerationCapability",
    "ImageGenerationRequest",
    "ImageGenerationResponse",
    "MAX_IMAGE_ATTACHMENT_BYTES",
]
