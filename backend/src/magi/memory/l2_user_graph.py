"""L2 user knowledge graph storage."""
from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class UserGraphNode:
    node_id: str
    node_type: str
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class UserGraphEdge:
    subject_id: str
    predicate: str
    object_id: str
    evidence_event_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0
    first_observed_at: float = 0.0
    last_observed_at: float = 0.0
    source_type_distribution: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subject_id": self.subject_id,
            "predicate": self.predicate,
            "object_id": self.object_id,
            "evidence_event_ids": list(self.evidence_event_ids),
            "confidence": self.confidence,
            "first_observed_at": self.first_observed_at,
            "last_observed_at": self.last_observed_at,
            "source_type_distribution": dict(self.source_type_distribution),
        }


class L2UserGraphStore:
    """Stores user-centric graph nodes and edges with evidence aggregation."""

    def __init__(self, persist_path: Optional[str] = None) -> None:
        self.persist_path = persist_path
        self._nodes: Dict[str, UserGraphNode] = {}
        self._edges: Dict[tuple[str, str, str], UserGraphEdge] = {}
        if self.persist_path:
            self._load()

    def upsert_node(self, node_id: str, node_type: str, attributes: Optional[Dict[str, Any]] = None) -> None:
        existing = self._nodes.get(node_id)
        merged_attributes = dict(existing.attributes if existing else {})
        merged_attributes.update(attributes or {})
        self._nodes[node_id] = UserGraphNode(node_id=node_id, node_type=node_type, attributes=merged_attributes)
        self._save()

    def upsert_edge(
        self,
        *,
        subject_id: str,
        predicate: str,
        object_id: str,
        evidence_event_ids: list[str],
        confidence: float,
        observed_at: float,
        source_type: str,
    ) -> None:
        key = (subject_id, predicate, object_id)
        edge = self._edges.get(key)
        if edge is None:
            edge = UserGraphEdge(
                subject_id=subject_id,
                predicate=predicate,
                object_id=object_id,
                evidence_event_ids=[],
                confidence=confidence,
                first_observed_at=observed_at,
                last_observed_at=observed_at,
                source_type_distribution={},
            )
            self._edges[key] = edge

        combined = list(dict.fromkeys([*edge.evidence_event_ids, *evidence_event_ids]))
        edge.evidence_event_ids = combined
        edge.confidence = max(edge.confidence, confidence)
        edge.first_observed_at = min(edge.first_observed_at or observed_at, observed_at)
        edge.last_observed_at = max(edge.last_observed_at, observed_at)
        edge.source_type_distribution[source_type] = edge.source_type_distribution.get(source_type, 0) + 1
        self._save()

    def get_edge(self, subject_id: str, predicate: str, object_id: str) -> Optional[UserGraphEdge]:
        return self._edges.get((subject_id, predicate, object_id))

    def get_edges(self, predicate: Optional[str] = None) -> list[UserGraphEdge]:
        edges = list(self._edges.values())
        if predicate:
            edges = [edge for edge in edges if edge.predicate == predicate]
        return edges

    def find_edges_by_event_id(self, event_id: str) -> list[UserGraphEdge]:
        return [edge for edge in self._edges.values() if event_id in edge.evidence_event_ids]

    def clear(self) -> int:
        total = len(self._edges)
        self._nodes.clear()
        self._edges.clear()
        self._save()
        return total

    def get_statistics(self) -> Dict[str, Any]:
        edge_types: Dict[str, int] = {}
        for edge in self._edges.values():
            edge_types[edge.predicate] = edge_types.get(edge.predicate, 0) + 1
        return {
            "total_nodes": len(self._nodes),
            "total_edges": len(self._edges),
            "edge_types": edge_types,
        }

    def _save(self) -> None:
        if not self.persist_path:
            return
        path = Path(self.persist_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            pickle.dumps(
                {
                    "nodes": self._nodes,
                    "edges": self._edges,
                }
            )
        )

    def _load(self) -> None:
        path = Path(self.persist_path)
        if not path.exists():
            return
        payload = pickle.loads(path.read_bytes())
        self._nodes = payload.get("nodes", {})
        self._edges = payload.get("edges", {})
