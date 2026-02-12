"""
L3: 事件语义层 (Event Semantics Layer)

使用向量嵌入存储和检索事件语义
支持语义相似度搜索

后端支持：
- 本地：sentence-transformers
- 远程：OpenAI/Anthropic Embedding API
"""
import logging
import time
import hashlib
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from collections import defaultdict

logger = logging.getLogger(__name__)


class EventEmbedding:
    """事件向量嵌入"""

    def __init__(
        self,
        event_id: str,
        embedding: List[float],
        text: str = "",
        metadata: Dict[str, Any] = None,
    ):
        self.event_id = event_id
        self.embedding = embedding
        self.text = text
        self.metadata = metadata or {}
        self.created_at = time.time()


class EmbeddingBackend:
    """嵌入后端基类"""

    async def initialize(self):
        """初始化后端"""
        pass

    async def generate(self, text: str) -> List[float]:
        """生成向量"""
        raise NotImplementedError

    @property
    def dimension(self) -> int:
        """向量维度"""
        raise NotImplementedError


class LocalEmbeddingBackend(EmbeddingBackend):
    """本地 sentence-transformers 后端"""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", dimension: int = 384):
        self.model_name = model_name
        self._dimension = dimension
        self._model = None
        self._model_loaded = False

    def _load_model(self):
        """加载嵌入模型"""
        if self._model_loaded:
            return

        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading local embedding model: {self.model_name}")
            self._model = SentenceTransformer(self.model_name)
            self._dimension = self._model.get_sentence_embedding_dimension()
            self._model_loaded = True
            logger.info(f"Local embedding model loaded, dimension: {self._dimension}")
        except ImportError:
            logger.warning("sentence-transformers not installed, using dummy embeddings")
            self._model = None
            self._model_loaded = True
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            self._model = None
            self._model_loaded = True

    async def generate(self, text: str) -> List[float]:
        """生成向量"""
        if not self._model_loaded:
            self._load_model()

        if self._model:
            embedding = self._model.encode(text, convert_to_numpy=True).tolist()
            return embedding
        else:
            # 生成简单的哈希向量作为回退
            text_hash = hashlib.md5(text.encode()).digest()
            # 扩展到目标维度
            while len(text_hash) < self._dimension // 8:
                text_hash += hashlib.sha1(text.encode()).digest()
            return [float(b) / 255.0 for b in text_hash[:self._dimension]]

    @property
    def dimension(self) -> int:
        return self._dimension


class RemoteEmbeddingBackend(EmbeddingBackend):
    """远程 LLM API 后端"""

    def __init__(
        self,
        llm_adapter,
        model: str = "text-embedding-3-small",
        dimension: int = 1536,
    ):
        """
        初始化远程嵌入后端

        Args:
            llm_adapter: LLM适配器实例
            model: 模型名称
            dimension: 向量维度
        """
        self.llm_adapter = llm_adapter
        self.model = model
        self._dimension = dimension

    async def initialize(self):
        """初始化后端"""
        # 如果llm_adapter有embedding相关设置，设置模型
        if hasattr(self.llm_adapter, 'set_embedding_model'):
            self.llm_adapter.set_embedding_model(self.model)
        # 更新实际维度
        if hasattr(self.llm_adapter, 'embedding_dimension'):
            self._dimension = self.llm_adapter.embedding_dimension

    async def generate(self, text: str) -> List[float]:
        """生成向量"""
        if not text or not text.strip():
            return [0.0] * self._dimension

        if not self.llm_adapter.supports_embeddings:
            logger.warning("LLM adapter does not support embeddings, using dummy")
            return self._dummy_embedding(text)

        embedding = await self.llm_adapter.get_embedding(text, self.model)
        if embedding is None:
            return self._dummy_embedding(text)
        return embedding

    def _dummy_embedding(self, text: str) -> List[float]:
        """生成简单的哈希向量作为回退"""
        text_hash = hashlib.md5(text.encode()).digest()
        while len(text_hash) < self._dimension // 8:
            text_hash += hashlib.sha1(text.encode()).digest()
        return [float(b) / 255.0 for b in text_hash[:self._dimension]]

    @property
    def dimension(self) -> int:
        return self._dimension


class EventEmbeddingStore:
    """
    事件向量嵌入存储

    支持向量生成、存储和相似度搜索
    """

    def __init__(
        self,
        backend: EmbeddingBackend = None,
        persist_path: str = None,
    ):
        """
        初始化向量存储

        Args:
            backend: 嵌入后端（不指定则使用默认本地后端）
            persist_path: 持久化文件路径
        """
        self.backend = backend or LocalEmbeddingBackend()
        self.persist_path = persist_path

        # 向量存储：{event_id: EventEmbedding}
        self._embeddings: Dict[str, EventEmbedding] = {}

        # 文本索引（用于重新生成嵌入）
        self._text_index: Dict[str, str] = {}  # {event_id: text}

        # 加载持久化数据
        if persist_path:
            self._load_from_disk()

    async def initialize(self):
        """初始化存储"""
        await self.backend.initialize()
        logger.info(f"Embedding store initialized, dimension: {self.backend.dimension}")

    async def _generate_embedding(self, text: str) -> List[float]:
        """
        生成文本的向量嵌入

        Args:
            text: 输入文本

        Returns:
            向量嵌入
        """
        return await self.backend.generate(text)

    async def add_event(
        self,
        event_id: str,
        text: str,
        metadata: Dict[str, Any] = None,
    ) -> List[float]:
        """
        添加事件并生成嵌入

        Args:
            event_id: 事件ID
            text: 事件文本内容
            metadata: 元数据

        Returns:
            生成的向量嵌入
        """
        embedding = await self._generate_embedding(text)

        self._embeddings[event_id] = EventEmbedding(
            event_id=event_id,
            embedding=embedding,
            text=text[:500],  # 保存前500字符用于重新生成
            metadata=metadata or {},
        )
        self._text_index[event_id] = text

        logger.debug(f"Embedding generated for event {event_id}")

        return embedding

    async def similarity_search(
        self,
        query_text: str,
        top_k: int = 10,
        threshold: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """
        语义相似度搜索

        Args:
            query_text: 查询文本
            top_k: 返回前K个结果
            threshold: 相似度阈值

        Returns:
            相似事件列表
        """
        if not self._embeddings:
            return []

        # 生成查询向量
        query_embedding = await self._generate_embedding(query_text)

        # 计算余弦相似度
        results = []
        for event_id, emb in self._embeddings.items():
            similarity = self._cosine_similarity(query_embedding, emb.embedding)

            if similarity >= threshold:
                results.append({
                    "event_id": event_id,
                    "similarity": similarity,
                    "text": emb.text,
                    "metadata": emb.metadata,
                })

        # 按相似度排序
        results.sort(key=lambda x: x["similarity"], reverse=True)

        return results[:top_k]

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """
        计算余弦相似度

        Args:
            vec1: 向量1
            vec2: 向量2

        Returns:
            相似度（0-1）
        """
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        magnitude1 = sum(a * a for a in vec1) ** 0.5
        magnitude2 = sum(b * b for b in vec2) ** 0.5

        if magnitude1 * magnitude2 == 0:
            return 0.0

        return dot_product / (magnitude1 * magnitude2)

    def get_embedding(self, event_id: str) -> Optional[List[float]]:
        """
        获取事件的嵌入

        Args:
            event_id: 事件ID

        Returns:
            向量嵌入
        """
        emb = self._embeddings.get(event_id)
        return emb.embedding if emb else None

    async def batch_add_events(
        self,
        events: List[Dict[str, Any]],
        text_field: str = "content",
    ):
        """
        批量添加事件

        Args:
            events: 事件列表
            text_field: 文本字段名
        """
        for event in events:
            event_id = event.get("id", event.get("event_id", ""))
            text = event.get(text_field, "") or str(event.get("data", {}))

            if event_id and text:
                await self.add_event(
                    event_id=event_id,
                    text=text,
                    metadata={"event_type": event.get("type", "unknown")},
                )

        logger.info(f"Added {len(events)} events to embedding store")

    def clear_old_embeddings(self, older_than_days: int = 30):
        """
        清理旧的嵌入数据

        Args:
            older_than_days: 清理多少天前的数据
        """
        cutoff_time = time.time() - (older_than_days * 86400)
        ids_to_remove = []

        for event_id, emb in self._embeddings.items():
            if emb.created_at < cutoff_time:
                ids_to_remove.append(event_id)

        for event_id in ids_to_remove:
            del self._embeddings[event_id]
            if event_id in self._text_index:
                del self._text_index[event_id]

        logger.info(f"Cleared {len(ids_to_remove)} old embeddings")

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_embeddings": len(self._embeddings),
            "dimension": self.backend.dimension,
            "backend": self.backend.__class__.__name__,
        }

    def _save_to_disk(self):
        """持久化到磁盘"""
        if not self.persist_path:
            return

        try:
            import json
            data = {
                "embeddings": {
                    event_id: {
                        "embedding": emb.embedding,
                        "text": emb.text,
                        "metadata": emb.metadata,
                        "created_at": emb.created_at,
                    }
                    for event_id, emb in self._embeddings.items()
                },
                "dimension": self.backend.dimension,
            }

            with open(self.persist_path, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            logger.debug(f"Embeddings saved to {self.persist_path}")
        except Exception as e:
            logger.error(f"Failed to save embeddings: {e}")

    def _load_from_disk(self):
        """从磁盘加载"""
        if not self.persist_path:
            return

        try:
            import json
            from pathlib import Path

            path = Path(self.persist_path)
            if not path.exists():
                return

            with open(self.persist_path, "r") as f:
                data = json.load(f)

            for event_id, emb_data in data.get("embeddings", {}).items():
                self._embeddings[event_id] = EventEmbedding(
                    event_id=event_id,
                    embedding=emb_data["embedding"],
                    text=emb_data.get("text", ""),
                    metadata=emb_data.get("metadata", {}),
                )
                self._embeddings[event_id].created_at = emb_data.get("created_at", time.time())
                self._text_index[event_id] = emb_data.get("text", "")

            logger.info(f"Embeddings loaded from {self.persist_path}")
        except Exception as e:
            logger.warning(f"Failed to load embeddings: {e}")


class HybridEventSearch:
    """
    混合事件搜索

    结合关键词搜索和语义搜索
    """

    def __init__(self, embedding_store: EventEmbeddingStore):
        self.embedding_store = embedding_store

    async def search(
        self,
        query: str,
        top_k: int = 10,
        semantic_weight: float = 0.7,
        keyword_weight: float = 0.3,
    ) -> List[Dict[str, Any]]:
        """
        混合搜索

        Args:
            query: 查询文本
            top_k: 返回前K个结果
            semantic_weight: 语义搜索权重
            keyword_weight: 关键词搜索权重

        Returns:
            搜索结果
        """
        # 语义搜索
        semantic_results = await self.embedding_store.similarity_search(
            query_text=query,
            top_k=top_k * 2,
            threshold=0.3,
        )

        # 关键词搜索
        keyword_results = self._keyword_search(query, top_k=top_k * 2)

        # 合并结果
        combined = self._combine_results(
            semantic_results,
            keyword_results,
            semantic_weight,
            keyword_weight,
        )

        return combined[:top_k]

    def _keyword_search(
        self,
        query: str,
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """关键词搜索"""
        query_lower = query.lower()
        results = []

        for event_id, emb in self.embedding_store._embeddings.items():
            text_lower = emb.text.lower()

            # 简单的关键词匹配
            if query_lower in text_lower:
                # 计算匹配分数
                score = len(query_lower) / len(text_lower)
                results.append({
                    "event_id": event_id,
                    "similarity": score,
                    "text": emb.text,
                    "metadata": emb.metadata,
                })

        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:top_k]

    def _combine_results(
        self,
        semantic_results: List[Dict],
        keyword_results: List[Dict],
        semantic_weight: float,
        keyword_weight: float,
    ) -> List[Dict]:
        """合并搜索结果"""
        combined = {}

        # 添加语义搜索结果
        for result in semantic_results:
            event_id = result["event_id"]
            combined[event_id] = {
                "event_id": event_id,
                "semantic_score": result["similarity"],
                "keyword_score": 0.0,
                "text": result["text"],
                "metadata": result["metadata"],
            }

        # 添加关键词搜索结果
        for result in keyword_results:
            event_id = result["event_id"]
            if event_id in combined:
                combined[event_id]["keyword_score"] = result["similarity"]
            else:
                combined[event_id] = {
                    "event_id": event_id,
                    "semantic_score": 0.0,
                    "keyword_score": result["similarity"],
                    "text": result["text"],
                    "metadata": result["metadata"],
                }

        # 计算综合分数
        for result in combined.values():
            result["combined_score"] = (
                result["semantic_score"] * semantic_weight +
                result["keyword_score"] * keyword_weight
            )

        # 排序
        results = list(combined.values())
        results.sort(key=lambda x: x["combined_score"], reverse=True)

        return results


def create_embedding_store(
    backend: str = "local",
    llm_adapter=None,
    local_model: str = "all-MiniLM-L6-v2",
    local_dimension: int = 384,
    remote_model: str = "text-embedding-3-small",
    remote_dimension: int = 1536,
    persist_path: str = None,
) -> EventEmbeddingStore:
    """
    创建嵌入存储的工厂函数

    Args:
        backend: 后端类型（local, openai, anthropic）
        llm_adapter: LLM适配器（远程后端需要）
        local_model: 本地模型名称
        local_dimension: 本地向量维度
        remote_model: 远程模型名称
        remote_dimension: 远程向量维度
        persist_path: 持久化路径

    Returns:
        EventEmbeddingStore 实例
    """
    if backend == "local":
        embedding_backend = LocalEmbeddingBackend(local_model, local_dimension)
    elif backend in ("openai", "anthropic"):
        if not llm_adapter:
            logger.warning(f"LLM adapter not provided for {backend}, falling back to local")
            embedding_backend = LocalEmbeddingBackend(local_model, local_dimension)
        else:
            embedding_backend = RemoteEmbeddingBackend(
                llm_adapter=llm_adapter,
                model=remote_model,
                dimension=remote_dimension,
            )
    else:
        logger.warning(f"Unknown backend {backend}, using local")
        embedding_backend = LocalEmbeddingBackend(local_model, local_dimension)

    return EventEmbeddingStore(
        backend=embedding_backend,
        persist_path=persist_path,
    )
