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
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        **kwargs
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
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        **kwargs
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
        **kwargs
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
        **kwargs
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
    def provider_name(self) -> str:
        """Get provider name (defaults to inferring from class name)"""
        return self.__class__.__name__.replace("Adapter", "").lower()

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

    @property
    def supports_embeddings(self) -> bool:
        """Whether embedding vectors are supported"""
        return False
