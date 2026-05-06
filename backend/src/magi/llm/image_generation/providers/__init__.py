"""Concrete image generation provider adapters."""

from .dashscope_image import DashScopeImageAdapter
from .gemini_predict import GeminiPredictImageAdapter
from .minimax_image import MiniMaxImageAdapter
from .openai_images import OpenAIImagesAdapter
from .zai_images import ZAIImagesAdapter

__all__ = [
	"DashScopeImageAdapter",
	"GeminiPredictImageAdapter",
	"MiniMaxImageAdapter",
	"OpenAIImagesAdapter",
	"ZAIImagesAdapter",
]
