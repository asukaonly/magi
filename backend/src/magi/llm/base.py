"""
LLM Adapter - Abstract base class
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, AsyncIterator, List


class LLMAdapter(ABC):
    """
    LLM Adapter abstract base class

    Defines a unified LLM invocation interface, supporting multiple LLM providers:
    - OpenAI (GPT-4, GPT-3.5)
    - Anthropic (Claude)
    - Local models (Llama.cpp)
    """

    @abstractmethod
    async def generate(
        self, prompt: str, max_tokens: Optional[int] = None, temperature: float = 0.7, **kwargs
    ) -> str:
        """
        Generate text (non-streaming)

        Args:
            prompt: Input prompt
            max_tokens: Maximum token count
            temperature: Temperature parameter (0.0-2.0)
            **kwargs: Additional parameters

        Returns:
            str: Generated text
        """
        pass

    @abstractmethod
    async def generate_stream(
        self, prompt: str, max_tokens: Optional[int] = None, temperature: float = 0.7, **kwargs
    ) -> AsyncIterator[str]:
        """
        Generate text (streaming)

        Args:
            prompt: Input prompt
            max_tokens: Maximum token count
            temperature: Temperature parameter (0.0-2.0)
            **kwargs: Additional parameters

        Yields:
            str: Generated text chunks
        """
        pass

    @abstractmethod
    async def chat(
        self,
        messages: list[Dict[str, str]],
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        **kwargs,
    ) -> str:
        """
        Dialogue generation (non-streaming)

        Args:
            messages: Dialogue history [{"role": "user", "content": "..."}, ...]
            max_tokens: Maximum token count
            temperature: Temperature parameter (0.0-2.0)
            **kwargs: Additional parameters

        Returns:
            str: Assistant's response
        """
        pass

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[Dict[str, str]],
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        **kwargs,
    ) -> AsyncIterator[str]:
        """
        Dialogue generation (streaming)

        Args:
            messages: Dialogue history
            max_tokens: Maximum token count
            temperature: Temperature parameter (0.0-2.0)
            **kwargs: Additional parameters

        Yields:
            str: Generated text chunks
        """
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Get model name"""
        pass

    @property
    def base_url(self) -> Optional[str]:
        """Get the adapter base URL, if one was configured."""
        return None

    @property
    def provider_name(self) -> str:
        """Get provider name (defaults to inferring from class name)"""
        return self.__class__.__name__.replace("Adapter", "").lower()

    @property
    def provider_plan(self) -> Optional[str]:
        """Get provider plan id, if one is active."""
        return None

    @property
    def provider_instance_id(self) -> Optional[str]:
        """Get the configured provider instance id, if available."""
        return getattr(self, "_provider_instance_id", None)

    async def get_embedding(
        self,
        text: str,
        model: Optional[str] = None,
    ) -> Optional[List[float]]:
        """
        Get text embedding vector (optional implementation)

        Args:
            text: Input text
            model: Embedding model name (optional)

        Returns:
            Embedding vector, or None if not supported
        """
        return None

    async def get_embeddings(
        self,
        texts: List[str],
        model: Optional[str] = None,
    ) -> List[Optional[List[float]]]:
        """
        Batch get embedding vectors (optional implementation)

        Args:
            texts: Input text list
            model: Embedding model name (optional)

        Returns:
            List of embedding vectors
        """
        return [await self.get_embedding(text, model) for text in texts]

    async def get_embedding_with_usage(
        self,
        text: str,
        model: Optional[str] = None,
    ) -> tuple[Optional[List[float]], int]:
        """
        Get a text embedding vector along with the prompt-token count.

        Default implementation delegates to :meth:`get_embedding` and reports 0
        tokens, so adapters that do not surface usage (e.g. local/free paths)
        stay free. Remote adapters should override to return real token counts.

        Returns:
            Tuple of (embedding vector or None, prompt token count)
        """
        return (await self.get_embedding(text, model), 0)

    async def get_embeddings_with_usage(
        self,
        texts: List[str],
        model: Optional[str] = None,
    ) -> tuple[List[Optional[List[float]]], int]:
        """
        Batch get embedding vectors along with the total prompt-token count.

        Default implementation delegates to :meth:`get_embeddings` and reports 0
        tokens, so adapters that do not surface usage (e.g. local/free paths)
        stay free. Remote adapters should override to return real token counts.

        Returns:
            Tuple of (list of embedding vectors, summed prompt token count)
        """
        return (await self.get_embeddings(texts, model), 0)

    @property
    def supports_embeddings(self) -> bool:
        """Whether embedding vectors are supported"""
        return False

    async def generate_image(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        size: str = "1024x1024",
        quality: str = "auto",
        n: int = 1,
    ) -> Optional[Dict[str, Any]]:
        """Generate an image from a text prompt (optional implementation).

        Args:
            prompt: Text description of the desired image.
            model: Image generation model name (optional, uses adapter default).
            size: Image dimensions, e.g. ``"1024x1024"``.
            quality: Generation quality hint (``"auto"``, ``"high"``, ``"medium"``, ``"low"``).
            n: Number of images to generate.

        Returns:
            Dict with ``images`` list and metadata, or ``None`` if not supported.
        """
        return None
