"""L2 event relation storage backed by in-memory graph + disk persistence."""

from __future__ import annotations

import logging
import pickle
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, DefaultDict, Dict, Iterable, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class EventRelation:
    """A directed relation between two events."""

    source_event_id: str
    target_event_id: str
    relation_type: str
    confidence: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_event_id": self.source_event_id,
            "target_event_id": self.target_event_id,
            "relation_type": self.relation_type,
            "confidence": self.confidence,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "EventRelation":
        return cls(
            source_event_id=str(payload["source_event_id"]),
            target_event_id=str(payload["target_event_id"]),
            relation_type=str(payload["relation_type"]),
            confidence=float(payload.get("confidence", 1.0)),
            metadata=dict(payload.get("metadata", {})),
        )


class EventRelationStore:
    """Stores event relations and exposes graph-oriented query helpers."""

    def __init__(self, persist_path: Optional[str] = None):
        self.persist_path = persist_path
        # source -> relation_type -> target -> EventRelation
        self._graph: DefaultDict[str, DefaultDict[str, Dict[str, EventRelation]]] = defaultdict(
            lambda: defaultdict(dict)
        )
        # target -> relation_type -> source -> EventRelation
        self._reverse_graph: DefaultDict[str, DefaultDict[str, Dict[str, EventRelation]]] = defaultdict(
            lambda: defaultdict(dict)
        )
        # event id -> event payload
        self._events: Dict[str, Dict[str, Any]] = {}
        # compatibility alias used by existing API layer
        self._relations = self._graph

        if self.persist_path:
            self._load_from_disk()

    def add_event(self, event_id: str, event_data: Dict[str, Any]) -> None:
        """Adds or updates an indexed event payload."""
        payload = dict(event_data)
        payload.setdefault("id", event_id)
        payload.setdefault("timestamp", time.time())
        self._events[event_id] = payload

    def add_relation(
        self,
        source_event_id: str,
        target_event_id: str,
        relation_type: str,
        confidence: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Adds/overwrites a directed relation."""
        relation = EventRelation(
            source_event_id=source_event_id,
            target_event_id=target_event_id,
            relation_type=relation_type,
            confidence=confidence,
            metadata=dict(metadata or {}),
        )
        self._graph[source_event_id][relation_type][target_event_id] = relation
        self._reverse_graph[target_event_id][relation_type][source_event_id] = relation

    def remove_event(self, event_id: str) -> None:
        """Removes an event and all connected relations."""
        self._events.pop(event_id, None)

        outgoing = self._graph.pop(event_id, {})
        for relation_type, targets in outgoing.items():
            for target_id in list(targets.keys()):
                self._reverse_graph[target_id][relation_type].pop(event_id, None)
                if not self._reverse_graph[target_id][relation_type]:
                    self._reverse_graph[target_id].pop(relation_type, None)
                if not self._reverse_graph[target_id]:
                    self._reverse_graph.pop(target_id, None)

        incoming = self._reverse_graph.pop(event_id, {})
        for relation_type, sources in incoming.items():
            for source_id in list(sources.keys()):
                self._graph[source_id][relation_type].pop(event_id, None)
                if not self._graph[source_id][relation_type]:
                    self._graph[source_id].pop(relation_type, None)
                if not self._graph[source_id]:
                    self._graph.pop(source_id, None)

    def clear(self) -> int:
        """Clears all indexed events and relations."""
        count = len(self._events)
        self._events.clear()
        self._graph.clear()
        self._reverse_graph.clear()
        return count

    def get_relations(
        self,
        event_id: str,
        relation_type: Optional[str] = None,
        direction: str = "outgoing",
    ) -> List[EventRelation]:
        """Returns relations connected to an event."""
        relations: List[EventRelation] = []
        include_outgoing = direction in {"outgoing", "both"}
        include_incoming = direction in {"incoming", "both"}

        if include_outgoing and event_id in self._graph:
            type_map = self._graph[event_id]
            selected_types: Iterable[str] = [relation_type] if relation_type else type_map.keys()
            for rel_type in selected_types:
                relations.extend(type_map.get(rel_type, {}).values())

        if include_incoming and event_id in self._reverse_graph:
            type_map = self._reverse_graph[event_id]
            selected_types = [relation_type] if relation_type else type_map.keys()
            for rel_type in selected_types:
                relations.extend(type_map.get(rel_type, {}).values())

        return relations

    def find_path(
        self,
        start_event_id: str,
        end_event_id: str,
        max_depth: int = 5,
        relation_types: Optional[List[str]] = None,
    ) -> List[str]:
        """Finds a path between two events by BFS."""
        if start_event_id == end_event_id:
            return [start_event_id]

        allowed = set(relation_types or [])
        queue: deque[tuple[str, int, List[str]]] = deque([(start_event_id, 0, [start_event_id])])
        visited: Set[str] = set()

        while queue:
            current_id, depth, path = queue.popleft()
            if depth >= max_depth or current_id in visited:
                continue
            visited.add(current_id)

            for relation in self.get_relations(current_id, direction="outgoing"):
                if allowed and relation.relation_type not in allowed:
                    continue
                target_id = relation.target_event_id
                if target_id == end_event_id:
                    return path + [target_id]
                if target_id not in visited:
                    queue.append((target_id, depth + 1, path + [target_id]))

        return []

    def get_related_events(
        self,
        event_id: str,
        relation_types: Optional[List[str]] = None,
        max_depth: int = 2,
    ) -> Dict[int, List[Dict[str, Any]]]:
        """Returns nearby events grouped by graph depth."""
        result: Dict[int, List[Dict[str, Any]]] = {0: [dict(self._events.get(event_id, {"id": event_id}))]}
        visited: Set[str] = {event_id}
        current_level = [event_id]
        allowed = set(relation_types or [])

        for depth in range(1, max_depth + 1):
            next_level: List[str] = []
            result[depth] = []
            for current_id in current_level:
                for relation in self.get_relations(current_id, direction="outgoing"):
                    if allowed and relation.relation_type not in allowed:
                        continue
                    target_id = relation.target_event_id
                    if target_id in visited:
                        continue
                    if target_id not in self._events:
                        continue
                    visited.add(target_id)
                    next_level.append(target_id)
                    payload = dict(self._events[target_id])
                    payload["relation"] = relation.to_dict()
                    result[depth].append(payload)
            if not next_level:
                break
            current_level = next_level

        return result

    def extract_relations_from_events(self, events: List[Dict[str, Any]], use_llm: bool = False) -> int:
        """Extracts baseline relations from event sequences."""
        _ = use_llm
        extracted = 0

        for idx, event in enumerate(events):
            event_id = str(event.get("id") or event.get("event_id") or "")
            if not event_id:
                continue
            self.add_event(event_id, event)

            if idx > 0:
                prev = events[idx - 1]
                prev_id = str(prev.get("id") or prev.get("event_id") or "")
                if prev_id:
                    self.add_relation(prev_id, event_id, relation_type="PRECEDE", confidence=1.0)
                    extracted += 1

        if self.persist_path:
            self._save_to_disk()

        return extracted

    def clear_old_relations(self, older_than_days: int = 30) -> int:
        """Clears events older than a retention threshold."""
        cutoff = time.time() - (older_than_days * 86400)
        old_event_ids = [
            event_id
            for event_id, payload in self._events.items()
            if float(payload.get("timestamp", 0.0)) < cutoff
        ]

        for event_id in old_event_ids:
            self.remove_event(event_id)

        if old_event_ids and self.persist_path:
            self._save_to_disk()

        return len(old_event_ids)

    def get_statistics(self) -> Dict[str, Any]:
        """Returns relation store metrics."""
        total_relations = 0
        relation_types: Dict[str, int] = defaultdict(int)
        for type_map in self._graph.values():
            for relation_type, targets in type_map.items():
                count = len(targets)
                total_relations += count
                relation_types[relation_type] += count

        total_events = len(self._events)
        return {
            "total_events": total_events,
            "total_relations": total_relations,
            "relation_types": dict(relation_types),
            "avg_relations_per_event": (total_relations / total_events) if total_events else 0.0,
        }

    def _save_to_disk(self) -> None:
        """Persists graph/index data to disk."""
        if not self.persist_path:
            return

        path = Path(self.persist_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "events": self._events,
            "relations": [
                relation.to_dict()
                for source_map in self._graph.values()
                for target_map in source_map.values()
                for relation in target_map.values()
            ],
        }

        try:
            with path.open("wb") as fp:
                pickle.dump(payload, fp)
        except Exception as exc:  # pragma: no cover - defensive path
            logger.warning("Failed to persist relation graph: %s", exc)

    # compatibility alias used by legacy callers
    _save = _save_to_disk

    def _load_from_disk(self) -> None:
        """Loads graph/index data from disk if present."""
        if not self.persist_path:
            return

        path = Path(self.persist_path)
        if not path.exists():
            return

        try:
            with path.open("rb") as fp:
                payload = pickle.load(fp)
        except Exception as exc:  # pragma: no cover - defensive path
            logger.warning("Failed to load relation graph: %s", exc)
            return

        self._events = dict(payload.get("events", {}))
        self._graph = defaultdict(lambda: defaultdict(dict))
        self._reverse_graph = defaultdict(lambda: defaultdict(dict))

        for item in payload.get("relations", []):
            relation = EventRelation.from_dict(item)
            self._graph[relation.source_event_id][relation.relation_type][relation.target_event_id] = relation
            self._reverse_graph[relation.target_event_id][relation.relation_type][relation.source_event_id] = relation

        self._relations = self._graph
