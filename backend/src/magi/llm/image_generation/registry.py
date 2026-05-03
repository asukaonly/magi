"""Protocol registry for image generation adapters."""

from __future__ import annotations

from typing import Type

from .base import ImageGenerationAdapter
from .providers.openai_images import OpenAIImagesAdapter

_PROTOCOL_REGISTRY: dict[str, Type[ImageGenerationAdapter]] = {
    "openai_images": OpenAIImagesAdapter,
}


def get_image_generation_adapter_class(
    protocol: str,
) -> Type[ImageGenerationAdapter] | None:
    """Return the adapter class registered for a native image protocol."""
    return _PROTOCOL_REGISTRY.get(str(protocol or "").strip().lower())


def is_registered_image_generation_protocol(protocol: str) -> bool:
    """Return whether a native image protocol has an implementation."""
    return get_image_generation_adapter_class(protocol) is not None


__all__ = [
    "get_image_generation_adapter_class",
    "is_registered_image_generation_protocol",
]
