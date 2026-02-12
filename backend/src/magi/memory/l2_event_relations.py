"""
L2: 事件关系层 (Event Relationships Layer)

使用图数据库存储和查询事件之间的关系
支持关系提取、图遍历、关系查询
"""
import logging
import time
from typing import Dict, Any, List, Optional, Set, Tuple
from datetime import datetime
from collections import defaultdict
import json

logger = logging.getLogger(__name__)


class EventRelation:
    """事件关系"""

    def __init__(
        self,
        source_event_id: str,
        target_event_id: str,
        relation_type: str,
        confidence: float = 1.0,
        metadata: Dict[str, Any] = None,
    ):
        self.source_event_id = source_event_id
        self.target_event_id = target_event_id
        self.relation_type = relation_type  # CAUSE, PRECEDE, FOLLOW, RELATED, etc.
        self.confidence = confidence
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_event_id": self.source_event_id,
            "target_event_id": self.target_event_id,
            "relation_type": self.relation_type,
            "confidence": self.confidence,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EventRelation":
        return cls(**data)


class EventRelationStore:
    """
    事件关系存储

    基于内存的图数据库实现（可扩展为 NetworkX 或 Neo4j）
    """

    # 关系类型定义
    RELATION_TYPES = {
        # 因果关系
        "CAUSE": "因果：A导致B发生",
        "PRECEDE": "时序：A发生在B之前",
        "FOLLOW": "跟随：A之后B紧随发生",

        # 语义关系
        "RELATED": "相关：A和B语义相关",
        "SAME_CONTEXT": "同上下文：A和B属于同一上下文",
        "SAME_USER": "同用户：A和B来自同一用户",

        # 实体关系
        "MENTION": "提及：A中提到了B中的实体",
        "REFERENCE": "引用：A引用了B",
        "RESPONSE": "响应：A是对B的响应",

        # 状态关系
        "TRIGGER": "触发：A触发了B",
        "BLOCK": "阻塞：A阻塞了B",
        "ENABLE": "使能：A使B成为可能",
    }

    def __init__(self, persist_path: str = None):
        """
        初始化事件关系存储

        Args:
            persist_path: 持久化文件路径（可选）
        """
        self.persist_path = persist_path

        # 图数据结构：{event_id: {relation_type: {target_event_id: EventRelation}}}
        self._graph: Dict[str, Dict[str, Dict[str, EventRelation]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(dict))
        )

        # 反向图：{event_id: {relation_type: {source_event_id: EventRelation}}}
        self._reverse_graph: Dict[str, Dict[str, Dict[str, EventRelation]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(dict))
        )

        # 事件索引：{event_id: event_data}
        self._events: Dict[str, Dict[str, Any]] = {}

        # 加载持久化数据
        if persist_path:
            self._load_from_disk()

    def add_event(self, event_id: str, event_data: Dict[str, Any]):
        """
        添加事件到索引

        Args:
            event_id: 事件ID
            event_data: 事件数据
        """
        self._events[event_id] = {
            "id": event_id,
            "data": event_data,
            "timestamp": time.time(),
        }
        logger.debug(f"Event indexed: {event_id}")

    def add_relation(
        self,
        source_event_id: str,
        target_event_id: str,
        relation_type: str,
        confidence: float = 1.0,
        metadata: Dict[str, Any] = None,
    ):
        """
        添加事件关系

        Args:
            source_event_id: 源事件ID
            target_event_id: 目标事件ID
            relation_type: 关系类型
            confidence: 置信度（0-1）
            metadata: 元数据
        """
        relation = EventRelation(
            source_event_id=source_event_id,
            target_event_id=target_event_id,
            relation_type=relation_type,
            confidence=confidence,
            metadata=metadata,
        )

        # 添加到正向图
        self._graph[source_event_id][relation_type][target_event_id] = relation

        # 添加到反向图
        self._reverse_graph[target_event_id][relation_type][source_event_id] = relation

        logger.debug(f"Relation added: {source_event_id} -> {target_event_id} ({relation_type})")

    def get_relations(
        self,
        event_id: str,
        relation_type: str = None,
        direction: str = "outgoing",
    ) -> List[EventRelation]:
        """
        获取事件的关系

        Args:
            event_id: 事件ID
            relation_type: 关系类型（None表示所有类型）
            direction: 方向（outgoing/incoming/both）

        Returns:
            关系列表
        """
        relations = []

        if direction in ("outgoing", "both"):
            graph = self._graph
            if event_id in graph:
                if relation_type:
                    types = {relation_type}
                else:
                    types = graph[event_id].keys()
                for rel_type in types:
                    for target_id, relation in graph[event_id][rel_type].items():
                        relations.append(relation)

        if direction in ("incoming", "both"):
            graph = self._reverse_graph
            if event_id in graph:
                if relation_type:
                    types = {relation_type}
                else:
                    types = graph[event_id].keys()
                for rel_type in types:
                    for source_id, relation in graph[event_id][rel_type].items():
                        relations.append(relation)

        return relations

    def find_path(
        self,
        start_event_id: str,
        end_event_id: str,
        max_depth: int = 5,
        relation_types: List[str] = None,
    ) -> List[str]:
        """
        查找两个事件之间的路径

        Args:
            start_event_id: 起始事件ID
            end_event_id: 目标事件ID
            max_depth: 最大深度
            relation_types: 允许的关系类型（None表示所有）

        Returns:
            事件ID路径
        """
        # BFS 搜索
        queue: List[Tuple[str, int, List[str]]] = [(start_event_id, 0, [start_event_id])]
        visited: Set[str] = set()

        while queue:
            current_event, depth, path = queue.pop(0)

            if current_event == end_event_id:
                return path

            if depth >= max_depth:
                continue

            if current_event in visited:
                continue

            visited.add(current_event)

            # 获取出边
            relations = self.get_relations(current_event, relation_types, "outgoing")
            for relation in relations:
                if relation.target_event_id not in visited:
                    new_path = path + [relation.target_event_id]
                    queue.append((relation.target_event_id, depth + 1, new_path))

        return []

    def get_related_events(
        self,
        event_id: str,
        relation_types: List[str] = None,
        max_depth: int = 2,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        获取相关事件（广度优先搜索）

        Args:
            event_id: 中心事件ID
            relation_types: 关系类型过滤
            max_depth: 最大深度

        Returns:
            相关事件字典：{depth: [events]}
        """
        result: Dict[int, List[Dict[str, Any]]] = {0: [self._events.get(event_id, {})]}
        visited: Set[str] = {event_id}
        current_level = [event_id]

        for depth in range(1, max_depth + 1):
            next_level = []
            result[depth] = []

            for current_event in current_level:
                relations = self.get_relations(current_event, relation_types, "outgoing")
                for relation in relations:
                    target_id = relation.target_event_id
                    if target_id not in visited and target_id in self._events:
                        visited.add(target_id)
                        next_level.append(target_id)
                        event_data = self._events[target_id].copy()
                        event_data["relation"] = relation.to_dict()
                        result[depth].append(event_data)

            current_level = next_level
            if not current_level:
                break

        return result

    def get_statistics(self) -> Dict[str, Any]:
        """
        获取关系图统计信息

        Returns:
            统计数据
        """
        total_relations = sum(
            len(targets)
            for event in self._graph.values()
            for types in event.values()
            for targets in types.values()
        )

        relation_counts = defaultdict(int)
        for event in self._graph.values():
            for rel_type, targets in event.items():
                relation_counts[rel_type] += len(targets)

        return {
            "total_events": len(self._events),
            "total_relations": total_relations,
            "relation_types": dict(relation_counts),
            "avg_relations_per_event": total_relations / len(self._events) if self._events else 0,
        }

    def extract_relations_from_events(
        self,
        events: List[Dict[str, Any]],
        use_llm: bool = False,
    ) -> int:
        """
        从事件列表中提取关系

        Args:
            events: 事件列表
            use_llm: 是否使用 LLM 提取（需要 LLM 支持）

        Returns:
            提取的关系数量
        """
        extracted_count = 0
        event_index = {e.get("id", e.get("event_id", "")): e for e in events}

        # 先添加所有事件到索引
        for event in events:
            event_id = event.get("id", event.get("event_id", ""))
            if event_id:
                self.add_event(event_id, event)

        # 提取关系
        for i, event in enumerate(events):
            event_id = event.get("id", event.get("event_id", ""))
            event_type = event.get("type", "")

            if not event_id:
                continue

            # 基于规则的结构化事件关系提取
            if event_type == "ToolExecution":
                # 工具执行 -> 任务完成
                self._extract_tool_relations(event, event_index)
                extracted_count += 1

            elif event_type == "LLMCall":
                # LLM 调用 -> 工具选择
                self._extract_llm_relations(event, event_index)
                extracted_count += 1

            elif event_type == "UserMessage":
                # 用户消息 -> LLM 响应
                self._extract_message_relations(event, event_index)
                extracted_count += 1

            # 提取时序关系（相邻事件）
            if i > 0:
                prev_event = events[i - 1]
                prev_event_id = prev_event.get("id", prev_event.get("event_id", ""))
                if prev_event_id:
                    self.add_relation(
                        source_event_id=prev_event_id,
                        target_event_id=event_id,
                        relation_type="PRECEDE",
                        confidence=1.0,
                    )
                    extracted_count += 1

        # 如果需要，可以使用 LLM 提取更复杂的关系
        if use_llm:
            # TODO: 实现 LLM 关系提取
            pass

        logger.info(f"Extracted {extracted_count} relations from {len(events)} events")

        # 持久化
        if self.persist_path:
            self._save_to_disk()

        return extracted_count

    def _extract_tool_relations(self, event: Dict[str, Any], event_index: Dict):
        """提取工具执行事件的关系"""
        event_id = event.get("id", "")
        data = event.get("data", {})

        # 工具执行通常是对某个任务的响应
        tool_name = data.get("tool", "")
        if tool_name:
            # 查找相关的 LLM 调用事件
            for other_event_id, other_event in event_index.items():
                if other_event.get("type") == "LLMCall":
                    llm_data = other_event.get("data", {})
                    if tool_name in str(llm_data):
                        self.add_relation(
                            source_event_id=other_event_id,
                            target_event_id=event_id,
                            relation_type="TRIGGER",
                            confidence=0.8,
                            metadata={"tool": tool_name},
                        )

    def _extract_llm_relations(self, event: Dict[str, Any], event_index: Dict):
        """提取 LLM 调用事件的关系"""
        event_id = event.get("id", "")
        data = event.get("data", {})

        # LLM 调用是对用户消息的响应
        user_id = data.get("user_id", "")
        if user_id:
            for other_event_id, other_event in event_index.items():
                if (other_event.get("type") == "UserMessage" and
                    other_event.get("data", {}).get("user_id") == user_id):
                    self.add_relation(
                        source_event_id=other_event_id,
                        target_event_id=event_id,
                        relation_type="TRIGGER",
                        confidence=0.9,
                    )

    def _extract_message_relations(self, event: Dict[str, Any], event_index: Dict):
        """提取用户消息事件的关系"""
        # 用户消息之间可能存在会话关系
        event_id = event.get("id", "")
        user_id = event.get("data", {}).get("user_id", "")

        if user_id:
            # 查找同一用户的其他消息
            for other_event_id, other_event in event_index.items():
                if (other_event.get("type") == "UserMessage" and
                    other_event.get("data", {}).get("user_id") == user_id and
                    other_event_id != event_id):
                    self.add_relation(
                        source_event_id=other_event_id,
                        target_event_id=event_id,
                        relation_type="SAME_CONTEXT",
                        confidence=0.7,
                        metadata={"user_id": user_id},
                    )

    def _save_to_disk(self):
        """持久化到磁盘"""
        if not self.persist_path:
            return

        try:
            import pickle
            data = {
                "graph": dict(self._graph),
                "reverse_graph": dict(self._reverse_graph),
                "events": self._events,
            }

            with open(self.persist_path, "wb") as f:
                pickle.dump(data, f)

            logger.debug(f"Event relations saved to {self.persist_path}")
        except Exception as e:
            logger.error(f"Failed to save event relations: {e}")

    def _load_from_disk(self):
        """从磁盘加载"""
        if not self.persist_path:
            return

        try:
            import pickle
            from pathlib import Path

            path = Path(self.persist_path)
            if not path.exists():
                return

            with open(self.persist_path, "rb") as f:
                data = pickle.load(f)

            self._graph = defaultdict(
                lambda: defaultdict(lambda: defaultdict(dict)),
                data.get("graph", {})
            )
            self._reverse_graph = defaultdict(
                lambda: defaultdict(lambda: defaultdict(dict)),
                data.get("reverse_graph", {})
            )
            self._events = data.get("events", {})

            logger.info(f"Event relations loaded from {self.persist_path}")
        except Exception as e:
            logger.warning(f"Failed to load event relations: {e}")

    def clear_old_relations(self, older_than_days: int = 30):
        """
        清理旧的关系数据

        Args:
            older_than_days: 清理多少天前的数据
        """
        cutoff_time = time.time() - (older_than_days * 86400)
        events_to_remove = []

        for event_id, event_data in self._events.items():
            if event_data.get("timestamp", 0) < cutoff_time:
                events_to_remove.append(event_id)

        for event_id in events_to_remove:
            # 删除事件的所有关系
            if event_id in self._graph:
                del self._graph[event_id]
            if event_id in self._reverse_graph:
                del self._reverse_graph[event_id]

            # 从其他事件的关系中删除
            for source_events in self._graph.values():
                for targets in source_events.values():
                    if event_id in targets:
                        del targets[event_id]

            del self._events[event_id]

        logger.info(f"Cleared {len(events_to_remove)} old events from relation store")

        if self.persist_path:
            self._save_to_disk()
