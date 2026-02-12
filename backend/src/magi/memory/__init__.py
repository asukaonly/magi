"""
记忆存储模块

五层记忆架构：
- L1: RawEventStore - 原始事件存储（完整事件信息）
- L2: EventRelationStore - 事件关系存储（图结构）
- L3: EventEmbeddingStore - 语义嵌入存储（向量搜索）
- L4: SummaryStore - 时间摘要存储（多粒度）
- L5: CapabilityMemory - 能力记忆存储（可复用能力）
"""
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from .self_memory import SelfMemory
from .other_memory import OtherMemory
from .raw_event_store import RawEventStore
from .l2_event_relations import EventRelationStore, EventRelation
from .l3_semantic_embeddings import (
    EventEmbeddingStore,
    EventEmbedding,
    HybridEventSearch,
    EmbeddingBackend,
    LocalEmbeddingBackend,
    RemoteEmbeddingBackend,
    create_embedding_store,
)
from .l4_summaries import SummaryStore, EventSummary, AutoSummarizer
from .l5_capabilities import CapabilityMemory, Capability

logger = logging.getLogger(__name__)


class UnifiedMemoryStore:
    """
    统一记忆存储

    整合五层记忆架构，提供统一的访问接口
    """

    def __init__(
        self,
        db_path: str = None,
        persist_dir: str = None,
        enable_embeddings: bool = True,
        enable_summaries: bool = True,
        enable_capabilities: bool = True,
        embedding_config: Dict[str, Any] = None,
        llm_adapter=None,
    ):
        """
        初始化统一记忆存储

        Args:
            db_path: 数据库路径（L1层）
            persist_dir: 持久化目录（L2-L5层）
            enable_embeddings: 是否启用语义嵌入（L3层）
            enable_summaries: 是否启用摘要（L4层）
            enable_capabilities: 是否启用能力记忆（L5层）
            embedding_config: 嵌入向量配置（backend, model等）
            llm_adapter: LLM适配器（用于远程嵌入）
        """
        from ..utils.runtime import get_runtime_paths

        runtime_paths = get_runtime_paths()

        # 设置默认路径
        if not db_path:
            db_path = str(runtime_paths.events_db_path)
        if not persist_dir:
            persist_dir = str(runtime_paths.memories_dir)

        persist_path = Path(persist_dir)

        # 解析嵌入配置
        emb_config = embedding_config or {}
        self._embedding_backend_type = emb_config.get("backend", "local")
        self._llm_adapter = llm_adapter

        # L1: 原始事件存储
        self.l1_raw = RawEventStore(db_path=db_path)

        # L2: 事件关系存储
        self.l2_relations = EventRelationStore(
            persist_path=str(persist_path / "relations.pkl")
        )

        # L3: 语义嵌入存储（根据配置选择后端）
        self.l3_embeddings = None
        self.l3_hybrid_search = None
        if enable_embeddings:
            self.l3_embeddings = create_embedding_store(
                backend=self._embedding_backend_type,
                llm_adapter=llm_adapter,
                local_model=emb_config.get("local_model", "all-MiniLM-L6-v2"),
                local_dimension=emb_config.get("local_dimension", 384),
                remote_model=emb_config.get("openai_model", "text-embedding-3-small"),
                remote_dimension=emb_config.get("remote_dimension", 1536),
                persist_path=str(persist_path / "embeddings.json"),
            )
            self.l3_hybrid_search = HybridEventSearch(self.l3_embeddings)

        # L4: 摘要存储
        self.l4_summaries = None
        self.l4_auto_summarizer = None
        if enable_summaries:
            self.l4_summaries = SummaryStore(
                persist_path=str(persist_path / "summaries.json")
            )
            self.l4_auto_summarizer = AutoSummarizer(self.l4_summaries)

        # L5: 能力记忆
        self.l5_capabilities = None
        if enable_capabilities:
            self.l5_capabilities = CapabilityMemory(
                persist_path=str(persist_path / "capabilities.json")
            )

        self._initialized = False

    async def initialize(self):
        """初始化所有存储层"""
        if self._initialized:
            return

        await self.l1_raw.init()

        if self.l3_embeddings:
            await self.l3_embeddings.initialize()

        self._initialized = True
        logger.info("Unified memory store initialized")

    async def add_event(
        self,
        event: Dict[str, Any],
        extract_relations: bool = True,
        generate_embeddings: bool = True,
    ) -> str:
        """
        添加事件到所有相关层级

        Args:
            event: 事件数据
            extract_relations: 是否提取关系
            generate_embeddings: 是否生成嵌入

        Returns:
            事件ID
        """
        event_id = event.get("id", event.get("event_id"))
        if not event_id:
            import uuid
            event_id = str(uuid.uuid4())
            event["id"] = event_id

        # L1: 存储原始事件（使用Event对象）
        from ..events.events import Event
        await self.l1_raw.store(Event(
            type=event.get("type", "unknown"),
            data=event.get("data", {}),
            timestamp=event.get("timestamp", 0),
            source=event.get("source", ""),
            metadata=event.get("metadata", {}),
        ))

        # L2: 添加事件到关系索引
        if extract_relations and event_id:
            self.l2_relations.add_event(event_id, event)

        # L3: 生成语义嵌入
        if generate_embeddings and self.l3_embeddings:
            text = self._extract_text_from_event(event)
            if text:
                await self.l3_embeddings.add_event(
                    event_id=event_id,
                    text=text,
                    metadata={"event_type": event.get("type", "unknown")},
                )

        # L4: 添加到摘要缓存
        if self.l4_summaries:
            self.l4_summaries.add_event(event)

        # L5: 记录任务尝试（如果是任务相关事件）
        if self.l5_capabilities and event.get("type") == "TaskCompleted":
            self._record_task_attempt(event)

        return event_id

    def _extract_text_from_event(self, event: Dict[str, Any]) -> str:
        """从事件中提取文本用于嵌入"""
        parts = []

        # 添加事件类型
        event_type = event.get("type", "")
        if event_type:
            parts.append(event_type)

        # 添加数据内容
        data = event.get("data", {})
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, str):
                    parts.append(value)
                elif isinstance(value, (int, float, bool)):
                    parts.append(f"{key}:{value}")

        return " ".join(parts) if parts else ""

    def _record_task_attempt(self, event: Dict[str, Any]):
        """记录任务尝试到能力记忆"""
        data = event.get("data", {})
        self.l5_capabilities.record_attempt(
            task_id=data.get("task_id", "unknown"),
            context=event.get("metadata", {}),
            action=data.get("action", {}),
            success=data.get("success", True),
            duration=data.get("duration", 0.0),
            error=data.get("error"),
        )

    async def search(
        self,
        query: str,
        search_type: str = "hybrid",
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        统一搜索接口

        Args:
            query: 查询文本
            search_type: 搜索类型（hybrid, semantic, keyword, relation）
            limit: 返回数量限制

        Returns:
            搜索结果
        """
        if search_type == "hybrid" and self.l3_hybrid_search:
            return await self.l3_hybrid_search.search(query, top_k=limit)
        elif search_type == "semantic" and self.l3_embeddings:
            return await self.l3_embeddings.similarity_search(query, top_k=limit)
        elif search_type == "keyword" and self.l3_hybrid_search:
            return self.l3_hybrid_search._keyword_search(query, top_k=limit)
        elif search_type == "relation":
            # 按关键词查找相关事件
            results = []
            for event_id, event_data in self.l2_relations._events.items():
                if query.lower() in str(event_data).lower():
                    results.append({"event_id": event_id, "data": event_data})
            return results[:limit]
        else:
            return []

    def get_related_events(
        self,
        event_id: str,
        max_depth: int = 2,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        获取相关事件（L2层）

        Args:
            event_id: 事件ID
            max_depth: 最大深度

        Returns:
            相关事件字典
        """
        return self.l2_relations.get_related_events(
            event_id=event_id,
            max_depth=max_depth,
        )

    def get_summary(
        self,
        period_type: str = "day",
        period_key: str = None,
    ) -> Optional[EventSummary]:
        """
        获取时间摘要（L4层）

        Args:
            period_type: 时间粒度（hour/day/week/month）
            period_key: 时间窗口标识

        Returns:
            事件摘要
        """
        if not self.l4_summaries:
            return None
        return self.l4_summaries.get_summary(period_type, period_key)

    def generate_summary(
        self,
        period_type: str = "day",
        period_key: str = None,
        force: bool = False,
    ) -> Optional[EventSummary]:
        """
        生成时间摘要（L4层）

        Args:
            period_type: 时间粒度
            period_key: 时间窗口标识
            force: 是否强制重新生成

        Returns:
            事件摘要
        """
        if not self.l4_summaries:
            return None
        return self.l4_summaries.generate_summary(period_type, period_key, force)

    def find_capability(
        self,
        context: Dict[str, Any],
        threshold: float = 0.5,
    ) -> Optional[Capability]:
        """
        查找匹配的能力（L5层）

        Args:
            context: 上下文信息
            threshold: 匹配阈值

        Returns:
            匹配的能力
        """
        if not self.l5_capabilities:
            return None
        return self.l5_capabilities.find_capability(context, threshold)

    def get_statistics(self) -> Dict[str, Any]:
        """获取所有层级的统计信息"""
        stats = {
            "l1_raw": {
                "db_path": self.l1_raw.db_path,
            },
            "l2_relations": self.l2_relations.get_statistics(),
        }

        if self.l3_embeddings:
            stats["l3_embeddings"] = self.l3_embeddings.get_statistics()

        if self.l4_summaries:
            stats["l4_summaries"] = self.l4_summaries.get_statistics()

        if self.l5_capabilities:
            stats["l5_capabilities"] = self.l5_capabilities.get_statistics()

        return stats

    async def cleanup_old_data(
        self,
        older_than_days: int = 30,
    ):
        """
        清理旧数据

        Args:
            older_than_days: 清理多少天前的数据
        """
        # L2: 清理旧关系
        self.l2_relations.clear_old_relations(older_than_days)

        # L3: 清理旧嵌入
        if self.l3_embeddings:
            self.l3_embeddings.clear_old_embeddings(older_than_days)

        # L4: 清理旧摘要
        if self.l4_summaries:
            self.l4_summaries.clear_old_summaries(older_than_days // 30)

        logger.info(f"Cleaned up data older than {older_than_days} days")


__all__ = [
    # 人格记忆
    "SelfMemory",
    "OtherMemory",

    # L1层
    "RawEventStore",

    # L2层
    "EventRelationStore",
    "EventRelation",

    # L3层
    "EventEmbeddingStore",
    "EventEmbedding",
    "HybridEventSearch",
    "EmbeddingBackend",
    "LocalEmbeddingBackend",
    "RemoteEmbeddingBackend",
    "create_embedding_store",

    # L4层
    "SummaryStore",
    "EventSummary",
    "AutoSummarizer",

    # L5层
    "CapabilityMemory",
    "Capability",

    # 统一接口
    "UnifiedMemoryStore",
]
