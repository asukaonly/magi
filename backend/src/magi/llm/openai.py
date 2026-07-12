"""
LLMAdapter - OpenAI Implementation
"""

from typing import Optional, Dict, Any, AsyncIterator, List
import httpx
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

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4",
        provider: str = "openai",
        base_url: Optional[str] = None,
        provider_plan: Optional[str] = None,
        timeout: int = 60,
        embedding_dimension: Optional[int] = None,
        proxy_url: Optional[str] = None,
    ):
        """
        Initialize OpenAIAdapter

        Args:
            api_key: OpenAI API key
            model: Model name
            base_url: Custom API endpoint (optional, for proxy or relay service)
            timeout: Request timeout in seconds
            proxy_url: HTTP/SOCKS5 proxy URL (optional). When omitted, connects directly.
        """
        self._model = model
        self._timeout = timeout
        self._provider = provider.lower()
        self._provider_plan = provider_plan
        self._embedding_dimension = (
            int(embedding_dimension) if embedding_dimension is not None else None
        )

        api_endpoint = base_url
        self._base_url = api_endpoint
        keyless_custom_endpoint = (
            not api_key
            and self._provider == "custom"
            and bool(api_endpoint)
        )

        async def remove_authorization_header(request: httpx.Request) -> None:
            request.headers.pop("authorization", None)

        # Always ignore system proxy; use explicit proxy_url when configured.
        http_client = httpx.AsyncClient(
            proxy=proxy_url,
            trust_env=False,
            event_hooks=(
                {"request": [remove_authorization_header]}
                if keyless_custom_endpoint
                else None
            ),
        )

        client_kwargs: Dict[str, Any] = {
            "api_key": api_key or "magi-keyless-custom",
            "timeout": timeout,
            "http_client": http_client,
        }
        if api_endpoint:
            client_kwargs["base_url"] = api_endpoint

        self._client = AsyncOpenAI(**client_kwargs)
        # Keep embedding model aligned with the scenario-selected model instead of a hardcoded default.
        self._embedding_model = model

    async def generate(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        system_prompt: Optional[str] = None,
        json_mode: bool = False,
        **kwargs,
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

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        )

        if not response.choices:
            return ""
        return response.choices[0].message.content or ""

    async def generate_stream(
        self, prompt: str, max_tokens: Optional[int] = None, temperature: float = 0.7, **kwargs
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
        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
            **kwargs,
        )

        async for chunk in stream:
            # Some OpenAI-compatible providers emit chunks with an empty
            # ``choices`` list — e.g. a final usage-only chunk (when
            # stream_options.include_usage is set) or a keep-alive. Skip them
            # instead of indexing ``[0]`` (which would IndexError).
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content

    async def chat(
        self,
        messages: list[Dict[str, str]],
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        **kwargs,
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
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        )

        if not response.choices:
            return ""
        return response.choices[0].message.content or ""

    async def chat_stream(
        self,
        messages: list[Dict[str, str]],
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        **kwargs,
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
        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
            **kwargs,
        )

        async for chunk in stream:
            # Some OpenAI-compatible providers emit chunks with an empty
            # ``choices`` list — e.g. a final usage-only chunk (when
            # stream_options.include_usage is set) or a keep-alive. Skip them
            # instead of indexing ``[0]`` (which would IndexError).
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content

    @property
    def model_name(self) -> str:
        """Get model name"""
        return self._model

    @property
    def provider_name(self) -> str:
        """Get provider name"""
        return self._provider

    @property
    def provider_plan(self) -> Optional[str]:
        """Get provider plan id."""
        return self._provider_plan

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

    async def get_embedding_with_usage(
        self,
        text: str,
        model: Optional[str] = None,
    ) -> tuple[Optional[List[float]], int]:
        """
        Get a text embedding vector along with its prompt-token usage.

        Mirrors :meth:`get_embedding` but also surfaces ``usage.prompt_tokens``
        from the embeddings response (embeddings have no completion tokens).

        Returns:
            Tuple of (embedding vector or None, prompt token count)
        """
        if not text or not text.strip():
            return (None, 0)

        embedding_model = model or self._embedding_model

        try:
            request_kwargs: Dict[str, Any] = {
                "model": embedding_model,
                "input": text,
            }
            if self._embedding_dimension is not None:
                request_kwargs["dimensions"] = self._embedding_dimension
            response = await self._client.embeddings.create(**request_kwargs)
            prompt_tokens = int(getattr(getattr(response, "usage", None), "prompt_tokens", 0) or 0)
            return (response.data[0].embedding, prompt_tokens)
        except Exception as e:
            import logging

            logging.getLogger(__name__).error(f"Failed to get embedding: {e}")
            return (None, 0)

    async def get_embeddings_with_usage(
        self,
        texts: List[str],
        model: Optional[str] = None,
    ) -> tuple[List[Optional[List[float]]], int]:
        """
        Batch get embedding vectors along with the total prompt-token usage.

        Mirrors :meth:`get_embeddings` but also surfaces ``usage.prompt_tokens``
        from the embeddings response. In the per-text fallback the token counts
        are summed across the individual requests.

        Returns:
            Tuple of (list of embedding vectors, summed prompt token count)
        """
        # Filter empty texts
        valid_texts = [(i, t) for i, t in enumerate(texts) if t and t.strip()]
        if not valid_texts:
            return ([None] * len(texts), 0)

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
            prompt_tokens = int(getattr(getattr(response, "usage", None), "prompt_tokens", 0) or 0)

            # Build result
            result = [None] * len(texts)
            for (i, _), embedding in zip(valid_texts, response.data):
                result[i] = embedding.embedding

            return (result, prompt_tokens)
        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Failed to get embeddings: {e}")
            # Fallback to individual retrieval, summing per-text usage.
            result = [None] * len(texts)
            summed_tokens = 0
            for i, t in enumerate(texts):
                vector, tokens = await self.get_embedding_with_usage(t, model)
                result[i] = vector
                summed_tokens += tokens
            return (result, summed_tokens)

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

    async def generate_image(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        size: str = "1024x1024",
        quality: str = "auto",
        n: int = 1,
    ) -> Optional[Dict[str, Any]]:
        """Generate images via OpenAI-compatible Images API.

        Returns:
            Dict with ``images`` list containing base64-encoded image data.
        """
        import logging

        logger = logging.getLogger(__name__)

        image_model = model or self._model
        try:
            response = await self._client.images.generate(
                model=image_model,
                prompt=prompt,
                n=n,
                size=size,
                quality=quality,
            )
            images = []
            for item in response.data:
                entry: Dict[str, Any] = {}
                if getattr(item, "b64_json", None):
                    entry["b64_json"] = item.b64_json
                if getattr(item, "url", None):
                    entry["url"] = item.url
                if getattr(item, "revised_prompt", None):
                    entry["revised_prompt"] = item.revised_prompt
                images.append(entry)
            return {"images": images, "model": image_model}
        except Exception as e:
            logger.error("Image generation failed: %s", e)
            raise
