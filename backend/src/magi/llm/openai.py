"""
LLM适配器 - OpenAI实现
"""
import asyncio
from typing import Optional, Dict, Any, AsyncIterator
from openai import AsyncOpenAI
from .base import LLMAdapter


class OpenAIAdapter(LLMAdapter):
    """
    OpenAI API适配器

    支持的模型：
    - GPT-4
    - GPT-4 Turbo
    - GPT-3.5 Turbo
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4",
        base_url: Optional[str] = None,
        api_base: Optional[str] = None,
        timeout: int = 60,
    ):
        """
        初始化OpenAI适配器

        Args:
            api_key: OpenAI API密钥
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

        self._client = AsyncOpenAI(**client_kwargs)

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
        生成文本（非流式）

        Args:
            prompt: 输入提示
            max_tokens: 最大token数
            temperature: 温度参数
            system_prompt: 系统提示（可选）
            json_mode: 是否启用JSON模式（强制返回有效JSON）
            **kwargs: 其他参数（传递给OpenAI API）

        Returns:
            str: 生成的文本
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # JSON mode: 强制返回有效JSON
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs
        )

        return response.choices[0].message.content or ""

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
        对话生成（非流式）

        Args:
            messages: 对话历史
            max_tokens: 最大token数
            temperature: 温度参数
            **kwargs: 其他参数

        Returns:
            str: 助手的回复
        """
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs
        )

        return response.choices[0].message.content or ""

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
        """获取模型名称"""
        return self._model
