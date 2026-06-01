"""Re-export shim — types now live in the SDK.

All host code (factory.py, providers/, tests) that does
    from .types import ImageArtifact, ...
continues to work unchanged, and class identity is preserved:
    magi.llm.image_generation.types.ImageArtifact
    is magi_plugin_sdk.image_generation.types.ImageArtifact
"""

from __future__ import annotations

from magi_plugin_sdk.image_generation.types import (  # noqa: F401
    ImageArtifact,
    ImageGenerationCapability,
    ImageGenerationRequest,
    ImageGenerationResponse,
)
