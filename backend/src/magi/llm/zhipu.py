"""
LLMAdapter - ZhipuAI (智谱) Implementation

Uses official zai-sdk for GLM models.
"""
import asyncio
import logging
from typing import Optional, Dict, Any, AsyncIterator, List

from .base import LLMAdapter

logger = logging.getLogger(__name__)


class ZhipuAdapter(LLMAdapter):
    """
    ZhipuAI (智谱) API Adapter

    Supported models:
    - glm-4-plus
    - glm-4-air
    - glm-4-airx
    - glm-4-flash
    - glm-4-long
    - glm-4v-plus (vision)
    - Embeddings (embedding-3)
    """

    # Default embedding model
    DEFAULT_EMBEDDING_MODEL = "embedding-3"

    def __init__(
        self,
        api_key: str,
        model: str = "glm-4-flash",
        provider: str = "zhipu",
        timeout: int = 120,
    ):
        """
        Initialize ZhipuAdapter

        Args:
            api_key: ZhipuAI API key
            model: Model name
            timeout: Request timeout in seconds
        """
        self._model = model
        self._timeout = timeout
        self._provider = provider.lower()

        # Lazy import to avoid dependency issues
        from zai import ZhipuAiClient
        self._client = ZhipuAiClient(api_key=api_key)
        self._embedding_model = self.DEFAULT_EMBEDDING_MODEL

    async def generate(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        system_prompt: Optional[str] = None,
        json_mode: bool = False,
        **kwargs
    ) -> str:
        """
        Generate text (non-streaming)

        Args:
            prompt: Input prompt
            max_tokens: Maximum tokens
            temperature: Temperature parameter
            system_prompt: System prompt (optional)
            json_mode: Whether to enable JSON mode

        Returns:
            Generated text
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # Build request kwargs
        request_kwargs = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            request_kwargs["max_tokens"] = max_tokens

        # JSON mode
        if json_mode:
            # ZhipuAI uses different parameter for structured output
            request_kwargs["response_format"] = {"type": "json_object"}

        # Keep API surface compatible but do not force provider-specific thinking flags.
        kwargs.pop("disable_thinking", None)

        # Merge any extra_body
        if "extra_body" in kwargs:
            existing = request_kwargs.get("extra_body", {})
            existing.update(kwargs.pop("extra_body"))
            request_kwargs["extra_body"] = existing

        request_kwargs.update(kwargs)

        # Run sync call in executor
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self._client.chat.completions.create(**request_kwargs)
        )

        return self._extract_content(response)

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
            max_tokens: Maximum tokens
            temperature: Temperature parameter

        Yields:
            Text chunks
        """
        request_kwargs = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens:
            request_kwargs["max_tokens"] = max_tokens

        request_kwargs.update(kwargs)

        # Run sync stream in executor with async wrapper
        loop = asyncio.get_event_loop()

        def sync_stream():
            return self._client.chat.completions.create(**request_kwargs)

        stream = await loop.run_in_executor(None, sync_stream)

        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def chat(
        self,
        messages: list[Dict[str, str]],
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        **kwargs
    ) -> str:
        """
        Chat generation (non-streaming)

        Args:
            messages: Chat history
            max_tokens: Maximum tokens
            temperature: Temperature parameter

        Returns:
            Assistant response
        """
        request_kwargs = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            request_kwargs["max_tokens"] = max_tokens

        # Keep API surface compatible but do not force provider-specific thinking flags.
        kwargs.pop("disable_thinking", None)

        # Merge any extra_body
        if "extra_body" in kwargs:
            existing = request_kwargs.get("extra_body", {})
            existing.update(kwargs.pop("extra_body"))
            request_kwargs["extra_body"] = existing

        request_kwargs.update(kwargs)

        # Run sync call in executor
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self._client.chat.completions.create(**request_kwargs)
        )

        return self._extract_content(response)

    async def chat_stream(
        self,
        messages: list[Dict[str, str]],
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        **kwargs
    ) -> AsyncIterator[str]:
        """
        Chat generation (streaming)

        Args:
            messages: Chat history
            max_tokens: Maximum tokens
            temperature: Temperature parameter

        Yields:
            Text chunks
        """
        request_kwargs = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens:
            request_kwargs["max_tokens"] = max_tokens

        request_kwargs.update(kwargs)

        loop = asyncio.get_event_loop()

        def sync_stream():
            return self._client.chat.completions.create(**request_kwargs)

        stream = await loop.run_in_executor(None, sync_stream)

        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def _extract_content(self, response) -> str:
        """Extract content from ZhipuAI response, handling thinking mode."""
        message = response.choices[0].message
        content = message.content or ""

        logger.debug(f"[ZhipuAI] Response model: {response.model}")
        logger.debug(f"[ZhipuAI] Response usage: {response.usage}")

        # Handle GLM thinking mode where content might be in reasoning_content
        if not content and hasattr(message, 'reasoning_content') and message.reasoning_content:
            content = message.reasoning_content
            logger.info("[ZhipuAI] Thinking mode detected, using reasoning_content")

        # Debug logging for empty/incomplete responses
        if not content or content == "{":
            logger.warning(f"[ZhipuAI] Incomplete/empty content: {repr(content)}")
            for attr in ['content', 'reasoning_content', 'role', 'tool_calls']:
                if hasattr(message, attr):
                    logger.warning(f"[ZhipuAI] message.{attr}: {getattr(message, attr)}")

        return content or ""

    @property
    def model_name(self) -> str:
        """Get model name"""
        return self._model

    @property
    def provider_name(self) -> str:
        """Get provider name"""
        return self._provider

    def set_embedding_model(self, model: str):
        """
        Set embedding model

        Args:
            model: Model name (e.g., embedding-3)
        """
        self._embedding_model = model

    async def get_embedding(
        self,
        text: str,
        model: Optional[str] = None,
    ) -> Optional[List[float]]:
        """
        Get text embedding vector

        Args:
            text: Input text
            model: Embedding model name (optional)

        Returns:
            Vector embedding
        """
        if not text or not text.strip():
            return None

        embedding_model = model or self._embedding_model

        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self._client.embeddings.create(
                    model=embedding_model,
                    input=text,
                )
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"Failed to get embedding: {e}")
            return None

    async def get_embeddings(
        self,
        texts: List[str],
        model: Optional[str] = None,
    ) -> List[Optional[List[float]]]:
        """
        Batch get embedding vectors

        Args:
            texts: Input text list
            model: Embedding model name (optional)

        Returns:
            Vector embedding list
        """
        # Filter empty texts
        valid_texts = [(i, t) for i, t in enumerate(texts) if t and t.strip()]
        if not valid_texts:
            return [None] * len(texts)

        embedding_model = model or self._embedding_model

        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self._client.embeddings.create(
                    model=embedding_model,
                    input=[t for _, t in valid_texts],
                )
            )

            # Build result
            result = [None] * len(texts)
            for (i, _), embedding in zip(valid_texts, response.data):
                result[i] = embedding.embedding

            return result
        except Exception as e:
            logger.error(f"Failed to get embeddings: {e}")
            # Fallback to individual requests
            return [await self.get_embedding(t, model) for t in texts]

    @property
    def supports_embeddings(self) -> bool:
        """Whether embeddings are supported"""
        return True

    @property
    def embedding_dimension(self) -> int:
        """
        Get current embedding model's vector dimension

        Returns:
            Vector dimension
        """
        dimensions = {
            "embedding-2": 1024,
            "embedding-3": 2048,
        }
        return dimensions.get(self._embedding_model, 2048)
