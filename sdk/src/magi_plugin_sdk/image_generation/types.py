"""Typed contracts for provider-native image generation.

Promoted to the SDK so plugins and tools can depend on these pure types
without importing host internals. The host re-exports these from
magi.llm.image_generation.types (shim) to preserve class identity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ImageGenerationCapability:
    """Provider/model-level image generation capability metadata."""

    supported_sizes: list[str] = field(default_factory=list)
    supported_qualities: list[str] = field(default_factory=list)
    supports_seed: bool = False
    supports_negative_prompt: bool = False
    supports_reference: bool = False
    max_n: int = 1


@dataclass(frozen=True)
class ImageGenerationRequest:
    """Provider-independent image generation request."""

    prompt: str
    model: str
    size: str = "1024x1024"
    quality: str = "auto"
    n: int = 1
    seed: int | None = None
    negative_prompt: str | None = None
    reference_images: list[bytes] | None = None


@dataclass(frozen=True)
class ImageArtifact:
    """One image returned by a provider before host-side persistence."""

    b64: str | None = None
    url: str | None = None
    mime: str = "image/png"
    revised_prompt: str | None = None
    seed: int | None = None
    raw_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ImageGenerationResponse:
    """Provider-independent image generation response."""

    images: list[ImageArtifact]
    model: str
    raw_metadata: dict[str, Any] = field(default_factory=dict)
