"""
LLM Adapter - Anthropic implementation
"""

from typing import Optional, Dict, Any, AsyncIterator
from contextlib import aclosing

from anthropic import AsyncAnthropic, DefaultAsyncHttpxClient
from .reasoning_dialect import anthropic_thinking_is_adaptive_only
from .base import LLMAdapter
from .model_context import automatic_output_reserve, unknown_model_context


def refusal_notice(has_text: bool) -> str:
    return ("\n\n" if has_text else "") + "The model provider declined to complete this request."


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
        provider_plan: Optional[str] = None,
        provider_instance_id: Optional[str] = None,
        timeout: int = 60,
        proxy_url: Optional[str] = None,
    ):
        """
        Initialize Anthropic Adapter

        Args:
            api_key: Anthropic API key
            model: Model name
            base_url: Custom API endpoint (optional, for proxy or relay services)
            timeout: Request timeout duration (seconds)
            proxy_url: HTTP/SOCKS5 proxy URL (optional). When omitted, connects directly.
        """
        self._model = model
        self._timeout = timeout
        self._provider_plan = provider_plan
        self._provider_instance_id = provider_instance_id

        api_endpoint = base_url
        self._base_url = api_endpoint

        # Always ignore system proxy; use explicit proxy_url when configured.
        http_client = DefaultAsyncHttpxClient(
            proxy=proxy_url,
            trust_env=False,
        )

        client_kwargs: Dict[str, Any] = {
            "api_key": api_key,
            "timeout": timeout,
            "http_client": http_client,
        }
        if api_endpoint:
            client_kwargs["base_url"] = api_endpoint

        self._client = AsyncAnthropic(**client_kwargs)

    async def generate(
        self, prompt: str, max_tokens: Optional[int] = None, temperature: float = 0.7, **kwargs
    ) -> str:
        return await self.chat([{"role": "user", "content": prompt}], max_tokens, temperature, **kwargs)

    async def generate_stream(
        self, prompt: str, max_tokens: Optional[int] = None, temperature: float = 0.7, **kwargs
    ) -> AsyncIterator[str]:
        async with aclosing(self.chat_stream([{"role": "user", "content": prompt}], max_tokens, temperature, **kwargs)) as stream:
            async for text in stream:
                yield text

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
            messages: Dialogue history
            max_tokens: Maximum token count
            temperature: Temperature parameter
            **kwargs: Additional parameters

        Returns:
            str: Assistant's response
        """
        kwargs = self._sampling_options(temperature, kwargs)
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens if max_tokens is not None else automatic_output_reserve(
                self.model_context or unknown_model_context(self)
            ),
            messages=messages,
            **kwargs,
        )

        text = "".join(block.text for block in response.content if block.type == "text")
        if getattr(response, "stop_reason", None) == "refusal":
            text += refusal_notice(bool(text))
        return text

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
            temperature: Temperature parameter
            **kwargs: Additional parameters

        Yields:
            str: Generated text chunks
        """
        kwargs = self._sampling_options(temperature, kwargs)
        stream = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens if max_tokens is not None else automatic_output_reserve(
                self.model_context or unknown_model_context(self)
            ),
            messages=messages,
            stream=True,
            **kwargs,
        )

        has_text = False
        try:
            async for event in stream:
                if event.type == "content_block_delta" and event.delta.type == "text_delta":
                    has_text = has_text or bool(event.delta.text)
                    yield event.delta.text
                elif event.type == "message_delta" and getattr(event.delta, "stop_reason", None) == "refusal":
                    yield refusal_notice(has_text)
        finally:
            await stream.close()

    def _sampling_options(self, temperature: float, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        if anthropic_thinking_is_adaptive_only(self._model):
            for key in ("temperature", "top_p", "top_k"):
                kwargs.pop(key, None)
        else:
            kwargs["temperature"] = temperature
        return kwargs

    @property
    def model_name(self) -> str:
        """Get model name"""
        return self._model

    @property
    def provider_name(self) -> str:
        """Get provider name"""
        return "anthropic"

    @property
    def provider_plan(self) -> Optional[str]:
        """Get provider plan id."""
        return self._provider_plan

    @property
    def provider_instance_id(self) -> Optional[str]:
        """Get the configured provider instance id."""
        return self._provider_instance_id

    @property
    def base_url(self) -> Optional[str]:
        """Get the configured API base URL."""
        return self._base_url
