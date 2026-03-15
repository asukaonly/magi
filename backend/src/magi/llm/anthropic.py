"""
LLM Adapter - Anthropic implementation
"""
from typing import Optional, Dict, Any, AsyncIterator
from anthropic import AsyncAnthropic
from .base import LLMAdapter
from ..config.constants import DEFAULT_MAX_TOKENS


class AnthropicAdapter(LLMAdapter):
    """
    Anthropic Claude API Adapter

    Supported models:
    - Claude 3 Opus
    - Claude 3 Sonnet
    - Claude 3 Haiku
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-3-opus-20240229",
        base_url: Optional[str] = None,
        api_base: Optional[str] = None,
        timeout: int = 60,
    ):
        """
        Initialize Anthropic Adapter

        Args:
            api_key: Anthropic API key
            model: Model name
            base_url: Custom API endpoint (optional, for proxy or relay services)
            api_base: Compatible with legacy configuration, equivalent to base_url
            timeout: Request timeout duration (seconds)
        """
        self._model = model
        self._timeout = timeout

        # Prefer base_url; fall back to api_base (backward compatible with legacy configuration)
        api_endpoint = base_url or api_base

        client_kwargs = {"api_key": api_key, "timeout": timeout}
        if api_endpoint:
            client_kwargs["base_url"] = api_endpoint

        self._client = AsyncAnthropic(**client_kwargs)

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
            temperature: Temperature parameter
            **kwargs: Additional parameters

        Returns:
            str: Generated text
        """
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens or DEFAULT_MAX_TOKENS,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
            **kwargs
        )

        if not response.content:
            return ""
        return response.content[0].text

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
            temperature: Temperature parameter
            **kwargs: Additional parameters

        Yields:
            str: Generated text chunks
        """
        stream = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens or DEFAULT_MAX_TOKENS,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
            **kwargs
        )

        async for event in stream:
            if event.type == "content_block_delta":
                yield event.delta.text

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
            messages: Dialogue history
            max_tokens: Maximum token count
            temperature: Temperature parameter
            **kwargs: Additional parameters

        Returns:
            str: Assistant's response
        """
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens or DEFAULT_MAX_TOKENS,
            temperature=temperature,
            messages=messages,
            **kwargs
        )

        if not response.content:
            return ""
        return response.content[0].text

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
            temperature: Temperature parameter
            **kwargs: Additional parameters

        Yields:
            str: Generated text chunks
        """
        stream = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens or DEFAULT_MAX_TOKENS,
            temperature=temperature,
            messages=messages,
            stream=True,
            **kwargs
        )

        async for event in stream:
            if event.type == "content_block_delta":
                yield event.delta.text

    @property
    def model_name(self) -> str:
        """Get model name"""
        return self._model

    @property
    def provider_name(self) -> str:
        """Get provider name"""
        return "anthropic"
