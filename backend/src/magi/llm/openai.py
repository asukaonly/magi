"""
LLMAdapter - OpenAIImplementation
"""
import asyncio
from typing import Optional, Dict, Any, AsyncIterator, List
from openai import AsyncOpenAI
from .base import LLMAdapter


class OpenAIAdapter(LLMAdapter):
    """
    OpenAI APIAdapter

    support的model：
    - GPT-4
    - GPT-4 Turbo
    - GPT-3.5 Turbo
    - Embeddings (text-embedding-3-small, text-embedding-3-large)
    """

    # default的embeddingmodel
    DEFAULT_EMBEDDING_MOdel = "text-embedding-3-small"

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4",
        provider: str = "openai",
        base_url: Optional[str] = None,
        api_base: Optional[str] = None,
        timeout: int = 60,
    ):
        """
        initializeOpenAIAdapter

        Args:
            api_key: OpenAI APIkey
            model: modelName
            base_url: customAPI endpoint（optional，如使用proxy或中转service）
            api_base: compatibleoldConfiguration，等同于base_url
            timeout: requesttimeout时间（seconds）
        """
        self._model = model
        self._timeout = timeout
        self._provider = provider.lower()

        # 优先使用base_url，nottt则使用api_base（compatibleoldConfiguration）
        api_endpoint = base_url or api_base

        client_kwargs = {"api_key": api_key, "timeout": timeout}
        if api_endpoint:
            client_kwargs["base_url"] = api_endpoint

        self._client = AsyncOpenAI(**client_kwargs)
        self._embedding_model = self.DEFAULT_EMBEDDING_MOdel

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
        generation文本（非流式）

        Args:
            prompt: Inputprompt
            max_tokens: maximumtoken数
            temperature: temperatureParameter
            system_prompt: 系统prompt（optional）
            json_mode: is notEnableJSONpattern（强制ReturnvalidJSON）
            **kwargs: otherParameter（传递给OpenAI API）

        Returns:
            str: generation的文本
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # JSON mode: 强制ReturnvalidJSON
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        # Handle thinking mode for GLM
        # - disable_thinking=True (default for most calls): Disable thinking mode
        # - disable_thinking=False or thinking_mode="enabled": Enable thinking mode
        thinking_disabled = kwargs.pop("disable_thinking", True)  # Default to disabled
        thinking_mode = kwargs.pop("thinking_mode", None)

        # Determine if thinking should be disabled
        should_disable_thinking = thinking_disabled or thinking_mode == "disabled"

        # Build extra_body for GLM thinking parameter
        extra_body = kwargs.pop("extra_body", {}) or {}
        if should_disable_thinking:
            extra_body["thinking"] = {"type": "disabled"}

        # Make the API call
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            extra_body=extra_body if extra_body else None,
            **kwargs
        )

        # Handle GLM's thinking mode where content is in reasoning_content
        message = response.choices[0].message
        content = message.content or ""

        # Debug: log raw response structure for troubleshooting
        import logging
        _logger = logging.getLogger(__name__)
        _logger.debug(f"[GLM] Response model: {response.model}")
        _logger.debug(f"[GLM] Response usage: {response.usage}")
        _logger.debug(f"[GLM] Number of choices: {len(response.choices)}")
        _logger.debug(f"[GLM] Raw message content: {repr(content[:200] if content else content)}")
        _logger.debug(f"[GLM] Message attributes: {dir(message)}")

        # Log the full raw response as dict for debugging
        try:
            if hasattr(response, 'model_dump'):
                _logger.debug(f"[GLM] Full response dict: {response.model_dump()}")
            elif hasattr(response, 'dict'):
                _logger.debug(f"[GLM] Full response dict: {response.dict()}")
        except Exception as e:
            _logger.debug(f"[GLM] Could not serialize response: {e}")
        if hasattr(message, 'reasoning_content'):
            _logger.debug(f"[GLM] reasoning_content: {repr(message.reasoning_content[:200] if message.reasoning_content else message.reasoning_content)}")

        # Check for reasoning_content (GLM thinking mode)
        if not content and hasattr(message, 'reasoning_content') and message.reasoning_content:
            content = message.reasoning_content
            _logger.info("GLM thinking mode detected, using reasoning_content")

        # Debug: log the response structure when content is empty or incomplete
        if not content or content == "{":
            _logger.warning(f"[GLM] Incomplete/empty content: {repr(content)}")
            _logger.warning(f"[GLM] Full response: {response}")
            _logger.warning(f"[GLM] Choice: {response.choices[0]}")
            _logger.warning(f"[GLM] Message: {message}")
            # Log all message attributes for debugging
            for attr in ['content', 'reasoning_content', 'role', 'function_call', 'tool_calls']:
                if hasattr(message, attr):
                    _logger.warning(f"[GLM] message.{attr}: {getattr(message, attr)}")

        return content or ""

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
        dialoguegeneration（非流式）

        Args:
            messages: dialoguehistory
            max_tokens: maximumtoken数
            temperature: temperatureParameter
            **kwargs: otherParameter

        Returns:
            str: 助手的response
        """
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs
        )

        # Handle GLM's thinking mode where content is in reasoning_content
        message = response.choices[0].message
        content = message.content or ""

        if not content and hasattr(message, 'reasoning_content') and message.reasoning_content:
            content = message.reasoning_content

        return content or ""

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
        """getmodelName"""
        return self._model

    @property
    def provider_name(self) -> str:
        """get提供商Name"""
        return self._provider

    def set_embedding_model(self, model: str):
        """
        Settingembeddingmodel

        Args:
            model: modelName（如 text-embedding-3-small）
        """
        self._embedding_model = model

    async def get_embedding(
        self,
        text: str,
        model: Optional[str] = None,
    ) -> Optional[List[float]]:
        """
        get文本的embeddingvector

        Args:
            text: Input文本
            model: embeddingmodelName（optional，default使用预设的embeddingmodel）

        Returns:
            vectorembedding
        """
        if not text or not text.strip():
            return None

        embedding_model = model or self._embedding_model

        try:
            response = await self._client.embeddings.create(
                model=embedding_model,
                input=text,
            )
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
        批量getembeddingvector

        Args:
            texts: Input文本list
            model: embeddingmodelName（optional）

        Returns:
            vectorembeddinglist
        """
        # filter空文本
        valid_texts = [(i, t) for i, t in enumerate(texts) if t and t.strip()]
        if not valid_texts:
            return [None] * len(texts)

        embedding_model = model or self._embedding_model

        try:
            # OpenAIsupport批量request
            response = await self._client.embeddings.create(
                model=embedding_model,
                input=[t for _, t in valid_texts],
            )

            # buildResult
            result = [None] * len(texts)
            for (i, _), embedding in zip(valid_texts, response.data):
                result[i] = embedding.embedding

            return result
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to get embeddings: {e}")
            # failure时逐个get
            return [await self.get_embedding(t, model) for t in texts]

    @property
    def supports_embeddings(self) -> bool:
        """is notsupportembeddingvector"""
        return True

    @property
    def embedding_dimension(self) -> int:
        """
        getcurrentembeddingmodel的vectordimension

        Returns:
            vectordimension
        """
        dimensions = {
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
            "text-embedding-ada-002": 1536,
        }
        return dimensions.get(self._embedding_model, 1536)
