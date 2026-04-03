"""
LLMAdapter - OpenAI Implementation
"""
from typing import Optional, Dict, Any, AsyncIterator, List
from openai import AsyncOpenAI
from .base import LLMAdapter


class OpenAIAdapter(LLMAdapter):
    """
    OpenAI API Adapter

    Supported models:
    - GPT-4
    - GPT-4 Turbo
    - GPT-3.5 Turbo
    - Embeddings (text-embedding-3-small, text-embedding-3-large)
    """

    # Legacy fallback value retained for compatibility references.
    DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
    GLM_DISABLED_THINKING_PAYLOAD = {"thinking": {"type": "disabled"}}
    DASHSCOPE_DISABLED_THINKING_PAYLOAD = {"enable_thinking": False}

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4",
        provider: str = "openai",
        base_url: Optional[str] = None,
        api_base: Optional[str] = None,
        timeout: int = 60,
        embedding_dimension: Optional[int] = None,
    ):
        """
        Initialize OpenAIAdapter

        Args:
            api_key: OpenAI API key
            model: Model name
            base_url: Custom API endpoint (optional, for proxy or relay service)
            api_base: Compatible with old config, same as base_url
            timeout: Request timeout in seconds
        """
        self._model = model
        self._timeout = timeout
        self._provider = provider.lower()
        self._embedding_dimension = int(embedding_dimension) if embedding_dimension is not None else None

        # Prefer base_url, fallback to api_base (compatible with old config)
        api_endpoint = base_url or api_base
        self._base_url = api_endpoint

        client_kwargs = {"api_key": api_key, "timeout": timeout}
        if api_endpoint:
            client_kwargs["base_url"] = api_endpoint

        self._client = AsyncOpenAI(**client_kwargs)
        # Keep embedding model aligned with the scenario-selected model instead of a hardcoded default.
        self._embedding_model = model

    def _apply_glm_thinking_control(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Strip ``disable_thinking`` from kwargs and, for GLM, inject extra_body toggle.

        .. deprecated::
            Thinking depth is now managed by ``LLMProviderBridge._apply_provider_options``.
            This method remains only for direct adapter calls that bypass the bridge.
        """
        payload = dict(kwargs)
        disable_thinking = payload.pop("disable_thinking", None)
        if disable_thinking is not True:
            return payload
        if self._provider not in ("glm", "dashscope"):
            return payload

        extra_body = payload.get("extra_body")
        if isinstance(extra_body, dict):
            merged_extra_body = dict(extra_body)
        else:
            merged_extra_body = {}

        if self._provider == "dashscope":
            merged_extra_body.update(self.DASHSCOPE_DISABLED_THINKING_PAYLOAD)
        else:
            merged_extra_body.update(self.GLM_DISABLED_THINKING_PAYLOAD)
        payload["extra_body"] = merged_extra_body
        return payload

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
            json_mode: Whether to enable JSON mode (force valid JSON response)
            **kwargs: Other parameters (passed to OpenAI API)

        Returns:
            Generated text
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # JSON mode: Force valid JSON response
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        kwargs = self._apply_glm_thinking_control(kwargs)

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs
        )

        if not response.choices:
            return ""
        return response.choices[0].message.content or ""

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
            **kwargs: Other parameters

        Yields:
            Text chunks
        """
        kwargs = self._apply_glm_thinking_control(kwargs)

        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
            **kwargs
        )

        async for chunk in stream:
            if chunk.choices[0].delta.content:
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
            **kwargs: Other parameters

        Returns:
            Assistant response
        """
        kwargs = self._apply_glm_thinking_control(kwargs)

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs
        )

        if not response.choices:
            return ""
        return response.choices[0].message.content or ""

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
            **kwargs: Other parameters

        Yields:
            Text chunks
        """
        kwargs = self._apply_glm_thinking_control(kwargs)

        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
            **kwargs
        )

        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    @property
    def model_name(self) -> str:
        """Get model name"""
        return self._model

    @property
    def provider_name(self) -> str:
        """Get provider name"""
        return self._provider

    @property
    def base_url(self) -> Optional[str]:
        """Get the configured API base URL."""
        return self._base_url

    def set_embedding_model(self, model: str):
        """
        Set embedding model

        Args:
            model: Model name (e.g., text-embedding-3-small)
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
            model: Embedding model name (optional, uses preset by default)

        Returns:
            Vector embedding
        """
        if not text or not text.strip():
            return None

        embedding_model = model or self._embedding_model

        try:
            request_kwargs: Dict[str, Any] = {
                "model": embedding_model,
                "input": text,
            }
            if self._embedding_dimension is not None:
                request_kwargs["dimensions"] = self._embedding_dimension
            response = await self._client.embeddings.create(**request_kwargs)
            return response.data[0].embedding
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Failed to get embedding: {e}")
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
            # OpenAI supports batch request
            request_kwargs: Dict[str, Any] = {
                "model": embedding_model,
                "input": [t for _, t in valid_texts],
            }
            if self._embedding_dimension is not None:
                request_kwargs["dimensions"] = self._embedding_dimension
            response = await self._client.embeddings.create(**request_kwargs)

            # Build result
            result = [None] * len(texts)
            for (i, _), embedding in zip(valid_texts, response.data):
                result[i] = embedding.embedding

            return result
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to get embeddings: {e}")
            # Fallback to individual retrieval
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
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
            "text-embedding-ada-002": 1536,
        }
        return dimensions.get(self._embedding_model, 1536)
