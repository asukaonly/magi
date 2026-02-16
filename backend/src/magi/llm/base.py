"""
LLMAdapter - 抽象Base class
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, AsyncIterator, List


class LLMAdapter(ABC):
    """
    LLMAdapter抽象Base class

    定义统一的LLM调用Interface，support多种LLM提供商：
    - OpenAI (GPT-4, GPT-3.5)
    - Anthropic (Claude)
    - 本地model (Llama.cpp)
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
        generation文本（非流式）

        Args:
            prompt: Inputprompt
            max_tokens: maximumtoken数
            temperature: temperatureParameter（0.0-2.0）
            **kwargs: otherParameter

        Returns:
            str: generation的文本
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
        generation文本（流式）

        Args:
            prompt: Inputprompt
            max_tokens: maximumtoken数
            temperature: temperatureParameter（0.0-2.0）
            **kwargs: otherParameter

        Yields:
            str: generation的文本片段
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
        dialoguegeneration（非流式）

        Args:
            messages: dialoguehistory [{"role": "user", "content": "..."}, ...]
            max_tokens: maximumtoken数
            temperature: temperatureParameter（0.0-2.0）
            **kwargs: otherParameter

        Returns:
            str: 助手的response
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
        dialoguegeneration（流式）

        Args:
            messages: dialoguehistory
            max_tokens: maximumtoken数
            temperature: temperatureParameter（0.0-2.0）
            **kwargs: otherParameter

        Yields:
            str: generation的文本片段
        """
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """getmodelName"""
        pass

    @property
    def provider_name(self) -> str:
        """get提供商Name（default使用Class名推断）"""
        return self.__class__.__name__.replace("Adapter", "").lower()

    async def get_embedding(
        self,
        text: str,
        model: Optional[str] = None,
    ) -> Optional[List[float]]:
        """
        get文本的embeddingvector（optionalImplementation）

        Args:
            text: Input文本
            model: embeddingmodelName（optional）

        Returns:
            vectorembedding，如果not support则ReturnNone
        """
        return None

    async def get_embeddings(
        self,
        texts: List[str],
        model: Optional[str] = None,
    ) -> List[Optional[List[float]]]:
        """
        批量getembeddingvector（optionalImplementation）

        Args:
            texts: Input文本list
            model: embeddingmodelName（optional）

        Returns:
            vectorembeddinglist
        """
        return [await self.get_embedding(text, model) for text in texts]

    @property
    def supports_embeddings(self) -> bool:
        """is notsupportembeddingvector"""
        return False
