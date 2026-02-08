"""
LLM适配器 - Anthropic实现
"""
from typing import Optional, Dict, Any, AsyncIterator
from anthropic import AsyncAnthropic
from .base import LLMAdapter


class AnthropicAdapter(LLMAdapter):
    """
    Anthropic Claude API适配器

    支持的模型：
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
        初始化Anthropic适配器

        Args:
            api_key: Anthropic API密钥
            model: 模型名称
            base_url: 自定义API endpoint（可选，如使用代理或中转服务）
            api_base: 兼容旧配置，等同于base_url
            timeout: 请求超时时间（秒）
        """
        self._model = model
        self._timeout = timeout

        # 优先使用base_url，否则使用api_base（兼容旧配置）
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
        生成文本（非流式）

        Args:
            prompt: 输入提示
            max_tokens: 最大token数
            temperature: 温度参数
            **kwargs: 其他参数

        Returns:
            str: 生成的文本
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
        生成文本（流式）

        Args:
            prompt: 输入提示
            max_tokens: 最大token数
            temperature: 温度参数
            **kwargs: 其他参数

        Yields:
            str: 生成的文本片段
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
        对话生成（非流式）

        Args:
            messages: 对话历史
            max_tokens: 最大token数
            temperature: 温度参数
            **kwargs: 其他参数

        Returns:
            str: 助手的回复
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
        对话生成（流式）

        Args:
            messages: 对话历史
            max_tokens: 最大token数
            temperature: 温度参数
            **kwargs: 其他参数

        Yields:
            str: 生成的文本片段
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
        """获取模型名称"""
        return self._model
