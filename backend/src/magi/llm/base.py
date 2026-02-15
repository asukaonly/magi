"""
LLM适配器 - 抽象基类
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, AsyncIterator, List


class LLMAdapter(ABC):
    """
    LLM适配器抽象基类

    定义统一的LLM调用接口，支持多种LLM提供商：
    - OpenAI (GPT-4, GPT-3.5)
    - Anthropic (Claude)
    - 本地模型 (Llama.cpp)
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
        生成文本（非流式）

        Args:
            prompt: 输入提示
            max_tokens: 最大token数
            temperature: 温度参数（0.0-2.0）
            **kwargs: 其他参数

        Returns:
            str: 生成的文本
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
        生成文本（流式）

        Args:
            prompt: 输入提示
            max_tokens: 最大token数
            temperature: 温度参数（0.0-2.0）
            **kwargs: 其他参数

        Yields:
            str: 生成的文本片段
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
        对话生成（非流式）

        Args:
            messages: 对话历史 [{"role": "user", "content": "..."}, ...]
            max_tokens: 最大token数
            temperature: 温度参数（0.0-2.0）
            **kwargs: 其他参数

        Returns:
            str: 助手的回复
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
        对话生成（流式）

        Args:
            messages: 对话历史
            max_tokens: 最大token数
            temperature: 温度参数（0.0-2.0）
            **kwargs: 其他参数

        Yields:
            str: 生成的文本片段
        """
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """获取模型名称"""
        pass

    @property
    def provider_name(self) -> str:
        """获取提供商名称（默认使用类名推断）"""
        return self.__class__.__name__.replace("Adapter", "").lower()

    async def get_embedding(
        self,
        text: str,
        model: Optional[str] = None,
    ) -> Optional[List[float]]:
        """
        获取文本的嵌入向量（可选实现）

        Args:
            text: 输入文本
            model: 嵌入模型名称（可选）

        Returns:
            向量嵌入，如果不支持则返回None
        """
        return None

    async def get_embeddings(
        self,
        texts: List[str],
        model: Optional[str] = None,
    ) -> List[Optional[List[float]]]:
        """
        批量获取嵌入向量（可选实现）

        Args:
            texts: 输入文本列表
            model: 嵌入模型名称（可选）

        Returns:
            向量嵌入列表
        """
        return [await self.get_embedding(text, model) for text in texts]

    @property
    def supports_embeddings(self) -> bool:
        """是否支持嵌入向量"""
        return False
