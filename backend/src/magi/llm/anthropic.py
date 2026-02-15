"""
LLMAdapter - AnthropicImplementation
"""
from typing import Optional, Dict, Any, AsyncIterator
from anthropic import AsyncAnthropic
from .base import LLMAdapter


class AnthropicAdapter(LLMAdapter):
    """
    Anthropic Claude APIAdapter

    support的model：
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
        initializeAnthropicAdapter

        Args:
            api_key: Anthropic APIkey
            model: modelName
            base_url: customAPI endpoint（optional，如使用proxy或中转service）
            api_base: compatibleoldConfiguration，等同于base_url
            timeout: requesttimeout时间（seconds）
        """
        self._model = model
        self._timeout = timeout

        # 优先使用base_url，nottt则使用api_base（compatibleoldConfiguration）
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
        generation文本（非流式）

        Args:
            prompt: Inputprompt
            max_tokens: maximumtoken数
            temperature: temperatureParameter
            **kwargs: otherParameter

        Returns:
            str: generation的文本
        """
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens or 4096,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
            **kwargs
        )

        return response.content[0].text

    async def generate_stream(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        **kwargs
    ) -> AsyncIterator[str]:
        """
        generation文本（流式）

        Args:
            prompt: Inputprompt
            max_tokens: maximumtoken数
            temperature: temperatureParameter
            **kwargs: otherParameter

        Yields:
            str: generation的文本片段
        """
        stream = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens or 4096,
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
        dialoguegeneration（非流式）

        Args:
            messages: dialoguehistory
            max_tokens: maximumtoken数
            temperature: temperatureParameter
            **kwargs: otherParameter

        Returns:
            str: 助手的response
        """
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens or 4096,
            temperature=temperature,
            messages=messages,
            **kwargs
        )

        return response.content[0].text

    async def chat_stream(
        self,
        messages: list[Dict[str, str]],
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        **kwargs
    ) -> AsyncIterator[str]:
        """
        dialoguegeneration（流式）

        Args:
            messages: dialoguehistory
            max_tokens: maximumtoken数
            temperature: temperatureParameter
            **kwargs: otherParameter

        Yields:
            str: generation的文本片段
        """
        stream = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens or 4096,
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
        """getmodelName"""
        return self._model

    @property
    def provider_name(self) -> str:
        """get提供商Name"""
        return "anthropic"
