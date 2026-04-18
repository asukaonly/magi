"""GroupedListAssembler — evidence for cross_session mode."""

from __future__ import annotations

import hashlib
from typing import Any

from ..models import RetrievalPayload, RetrievalQuery
from .base import GroupedListEvidence


class GroupedListAssembler:
    """Group evidence by entity/topic across sessions."""

    def assemble(
        self,
        payload: RetrievalPayload,
        request: RetrievalQuery,
    ) -> GroupedListEvidence:
        group_map: dict[str, dict[str, Any]] = {}
        dedup_set: set[str] = set()

        # 1. Group L2 entity cards
        for card in payload.l2_entity_cards:
            key = card.get("entity_id", card.get("name", "unknown"))
            grp = group_map.setdefault(key, {
                "entity": key,
                "items": [],
                "count": 0,
            })
            grp["items"].append(card)
            grp["count"] += 1

        # 2. Group L2 relationships by subject
        for rel in payload.l2_relationships:
            subject = rel.get("subject_id", "unknown")
            grp = group_map.setdefault(subject, {
                "entity": subject,
                "items": [],
                "count": 0,
            })
            content_hash = _content_hash(rel.get("natural_summary", ""))
            if content_hash not in dedup_set:
                dedup_set.add(content_hash)
                grp["items"].append(rel)
                grp["count"] += 1

        # 3. Group L2 episodes by dominant_mode
        for ep in payload.l2_episodes:
            mode = ep.get("dominant_mode") or "general"
            grp = group_map.setdefault(mode, {
                "entity": mode,
                "items": [],
                "count": 0,
            })
            grp["items"].append(ep)
            grp["count"] += 1

        # 4. Scatter L1 events by source
        for evt in payload.l1_events:
            source = evt.get("source") or "event"
            grp = group_map.setdefault(source, {
                "entity": source,
                "items": [],
                "count": 0,
            })
            content_hash = _content_hash(evt.get("summary") or evt.get("content", ""))
            if content_hash not in dedup_set:
                dedup_set.add(content_hash)
                grp["items"].append(evt)
                grp["count"] += 1

        groups = sorted(group_map.values(), key=lambda g: g["count"], reverse=True)
        total = sum(g["count"] for g in groups)

        return GroupedListEvidence(
            groups=groups,
            dedup_hints=list(dedup_set)[:50],
            total_matches=total,
        )


def _content_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:12]
