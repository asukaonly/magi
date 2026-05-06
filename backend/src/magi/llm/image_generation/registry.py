"""Protocol registry for image generation adapters."""

from __future__ import annotations

from typing import Type

from .base import ImageGenerationAdapter
from .providers.dashscope_image import DashScopeImageAdapter
from .providers.gemini_predict import GeminiPredictImageAdapter
from .providers.minimax_image import MiniMaxImageAdapter
from .providers.openai_images import OpenAIImagesAdapter
from .providers.zai_images import ZAIImagesAdapter

_PROTOCOL_REGISTRY: dict[str, Type[ImageGenerationAdapter]] = {
    "dashscope_multimodal_image": DashScopeImageAdapter,
    "gemini_predict": GeminiPredictImageAdapter,
    "minimax_image": MiniMaxImageAdapter,
    "openai_images": OpenAIImagesAdapter,
    "zai_images": ZAIImagesAdapter,
}


def get_image_generation_adapter_class(
    protocol: str,
) -> Type[ImageGenerationAdapter] | None:
    """Return the adapter class registered for a native image protocol."""
    return _PROTOCOL_REGISTRY.get(str(protocol or "").strip().lower())


def is_registered_image_generation_protocol(protocol: str) -> bool:
    """Return whether a native image protocol has an implementation."""
    return get_image_generation_adapter_class(protocol) is not None


def registered_image_generation_protocols() -> list[str]:
    """Return implemented native image generation protocols."""
    return sorted(_PROTOCOL_REGISTRY)


__all__ = [
    "get_image_generation_adapter_class",
    "is_registered_image_generation_protocol",
    "registered_image_generation_protocols",
]
