"""
Memory Storagemodule

五层memoryarchitecture：
- L1: RawEventStore - Raw event Storage（完整eventinfo）
- L2: EventRelationStore - eventrelationshipstorage（graphstructure）
- L3: eventEmbeddingStore - Semantic Embeddingsstorage（vectorsearch）
- L4: SummaryStore - Time Summariesstorage（多粒度）
- L5: CapabilityMemory - capabilityMemory Storage（可复用capability）
"""
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from .self_memory import SelfMemory
from .other_memory import OtherMemory
from .raw_event_store import RawEventStore
from .l2_event_relations import EventRelationStore, EventRelation
from .l3_semantic_embeddings import (
    eventEmbeddingStore,
    EventEmbedding,
    HybrideventSearch,
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
    Unified Memory Storage

    整合五层memoryarchitecture，提供统一的访问Interface
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
        initializeUnified Memory Storage

        Args:
            db_path: databasepath（L1层）
            persist_dir: 持久化directory（L2-L5层）
            enable_embeddings: is notEnableSemantic Embeddings（L3层）
            enable_summaries: is notEnablesummary（L4层）
            enable_capabilities: is notEnablecapabilitymemory（L5层）
            embedding_config: embeddingvectorConfiguration（backend, model等）
            llm_adapter: LLMAdapter（用于远程embedding）
        """
        from ..utils.runtime import get_runtime_paths

        runtime_paths = get_runtime_paths()

        # Settingdefaultpath
        if not db_path:
            db_path = str(runtime_paths.events_db_path)
        if not persist_dir:
            persist_dir = str(runtime_paths.memories_dir)

        persist_path = Path(persist_dir)

        # parseembeddingConfiguration
        emb_config = embedding_config or {}
        self._embedding_backend_type = emb_config.get("backend", "local")
        self._llm_adapter = llm_adapter

        # L1: Raw event Storage
        self.l1_raw = RawEventStore(db_path=db_path)

        # L2: eventrelationshipstorage
        self.l2_relations = EventRelationStore(
            persist_path=str(persist_path / "relations.pkl")
        )

        # L3: Semantic Embeddingsstorage（根据Configuration选择后端）
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
            self.l3_hybrid_search = HybrideventSearch(self.l3_embeddings)

        # L4: summarystorage
        self.l4_summaries = None
        self.l4_auto_summarizer = None
        if enable_summaries:
            self.l4_summaries = SummaryStore(
                persist_path=str(persist_path / "summaries.json")
            )
            self.l4_auto_summarizer = AutoSummarizer(self.l4_summaries)

        # L5: capabilitymemory
        self.l5_capabilities = None
        if enable_capabilities:
            self.l5_capabilities = CapabilityMemory(
                persist_path=str(persist_path / "capabilities.json")
            )

        self._initialized = False

    async def initialize(self):
        """initializeallstorage层"""
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
        addevent到allrelated层级

        Args:
            event: eventdata
            extract_relations: is not提取relationship
            generate_embeddings: is notgenerationembedding

        Returns:
            eventid
        """
        event_id = event.get("id", event.get("event_id"))
        if not event_id:
            import uuid
            event_id = str(uuid.uuid4())
            event["id"] = event_id

        # L1: storage原始event（使用eventObject）
        from ..events.events import Event
        await self.l1_raw.store(event(
            type=event.get("type", "unknown"),
            data=event.get("data", {}),
            timestamp=event.get("timestamp", 0),
            source=event.get("source", ""),
            metadata=event.get("metadata", {}),
        ))

        # L2: addevent到relationshipindex
        if extract_relations and event_id:
            self.l2_relations.add_event(event_id, event)

        # L3: generationSemantic Embeddings
        if generate_embeddings and self.l3_embeddings:
            text = self._extract_text_from_event(event)
            if text:
                await self.l3_embeddings.add_event(
                    event_id=event_id,
                    text=text,
                    metadata={"event_type": event.get("type", "unknown")},
                )

        # L4: add到summarycache
        if self.l4_summaries:
            self.l4_summaries.add_event(event)

        # L5: record任务尝试（如果is任务relatedevent）
        if self.l5_capabilities and event.get("type") == "TaskCompleted":
            self._record_task_attempt(event)

        return event_id

    def _extract_text_from_event(self, Event: Dict[str, Any]) -> str:
        """从event中提取文本用于embedding"""
        parts = []

        # addeventtype
        event_type = event.get("type", "")
        if event_type:
            parts.append(event_type)

        # adddataContent
        data = event.get("data", {})
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, str):
                    parts.append(value)
                elif isinstance(value, (int, float, bool)):
                    parts.append(f"{key}:{value}")

        return " ".join(parts) if parts else ""

    def _record_task_attempt(self, Event: Dict[str, Any]):
        """record任务尝试到capabilitymemory"""
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
        统一searchInterface

        Args:
            query: query文本
            search_type: searchtype（hybrid, semantic, keyword, relation）
            limit: Returnquantitylimitation

        Returns:
            searchResult
        """
        if search_type == "hybrid" and self.l3_hybrid_search:
            return await self.l3_hybrid_search.search(query, top_k=limit)
        elif search_type == "semantic" and self.l3_embeddings:
            return await self.l3_embeddings.similarity_search(query, top_k=limit)
        elif search_type == "keyword" and self.l3_hybrid_search:
            return self.l3_hybrid_search._keyword_search(query, top_k=limit)
        elif search_type == "relation":
            # 按关key词查找relatedevent
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
        getrelatedevent（L2层）

        Args:
            event_id: eventid
            max_depth: maximumdepth

        Returns:
            relatedeventdictionary
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
        getTime Summaries（L4层）

        Args:
            period_type: 时间粒度（hour/day/week/month）
            period_key: 时间窗口identifier

        Returns:
            eventsummary
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
        generationTime Summaries（L4层）

        Args:
            period_type: 时间粒度
            period_key: 时间窗口identifier
            force: is not强制重newgeneration

        Returns:
            eventsummary
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
        查找匹配的capability（L5层）

        Args:
            context: contextinfo
            threshold: 匹配阈Value

        Returns:
            匹配的capability
        """
        if not self.l5_capabilities:
            return None
        return self.l5_capabilities.find_capability(context, threshold)

    def get_statistics(self) -> Dict[str, Any]:
        """getall层级的statisticsinfo"""
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
        清理olddata

        Args:
            older_than_days: 清理多少days前的data
        """
        # L2: 清理oldrelationship
        self.l2_relations.clear_old_relations(older_than_days)

        # L3: 清理oldembedding
        if self.l3_embeddings:
            self.l3_embeddings.clear_old_embeddings(older_than_days)

        # L4: 清理oldsummary
        if self.l4_summaries:
            self.l4_summaries.clear_old_summaries(older_than_days // 30)

        logger.info(f"Cleaned up data older than {older_than_days} days")


__all__ = [
    # personalitymemory
    "SelfMemory",
    "OtherMemory",

    # L1层
    "RawEventStore",

    # L2层
    "EventRelationStore",
    "EventRelation",

    # L3层
    "eventEmbeddingStore",
    "EventEmbedding",
    "HybrideventSearch",
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

    # 统一Interface
    "UnifiedMemoryStore",
]
