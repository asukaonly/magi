"""Unified discovery index for runtime tool and skill recommendations."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


_DISCOVERY_SYNONYMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("日程", ("calendar", "schedule")),
    ("日历", ("calendar", "schedule")),
    ("会议", ("meeting", "calendar")),
    ("空档", ("availability", "free", "busy", "slot")),
    ("空闲", ("availability", "free", "busy", "slot")),
    ("档期", ("availability", "schedule", "slot")),
    ("可用时间", ("availability", "free", "busy", "slot")),
    ("安排", ("schedule", "planning")),
    ("照片", ("photo", "image", "picture")),
    ("图片", ("image", "photo", "picture")),
    ("天气", ("weather", "forecast")),
    ("网页", ("web", "fetch", "browser")),
    ("搜索", ("search", "web")),
    ("代码", ("code", "file", "grep")),
    ("文件", ("file", "read", "write")),
)
_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+", re.IGNORECASE)


@dataclass(slots=True)
class ToolDiscoveryCandidate:
    """One searchable tool or skill candidate."""

    name: str
    kind: str
    source: str
    description: str
    category: str = ""
    tags: tuple[str, ...] = ()
    argument_hint: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def search_text(self) -> str:
        metadata_parts: list[str] = []
        for key in ("task_intents", "domains", "operations"):
            value = self.metadata.get(key)
            if isinstance(value, list):
                metadata_parts.extend(str(item) for item in value)
        return " ".join(
            [
                self.name,
                self.kind,
                self.description,
                self.category,
                self.argument_hint,
                " ".join(self.tags),
                " ".join(metadata_parts),
            ]
        )


class ToolDiscoveryIndex:
    """Searchable index spanning registered tools and skills."""

    def __init__(self, candidates: list[ToolDiscoveryCandidate]) -> None:
        self._candidates = list(candidates)

    @classmethod
    def from_registry(
        cls,
        registry: Any,
        *,
        enabled_features: list[str] | None = None,
    ) -> "ToolDiscoveryIndex":
        candidates: list[ToolDiscoveryCandidate] = []
        for tool_name in registry.list_tools(enabled_features=enabled_features):
            info = registry.get_tool_info(tool_name) or {}
            candidates.append(
                ToolDiscoveryCandidate(
                    name=str(info.get("name") or tool_name),
                    kind="tool",
                    source=_infer_tool_source(
                        name=str(info.get("name") or tool_name),
                        category=str(info.get("category") or ""),
                        metadata=dict(info.get("metadata") or {}),
                    ),
                    description=str(info.get("description") or ""),
                    category=str(info.get("category") or ""),
                    tags=tuple(str(tag) for tag in (info.get("tags") or [])),
                    metadata=dict(info.get("metadata") or {}),
                )
            )

        for skill_name in registry.get_skill_names():
            metadata = registry.get_skill_metadata(skill_name)
            if metadata is None:
                continue
            candidates.append(
                ToolDiscoveryCandidate(
                    name=skill_name,
                    kind="skill",
                    source="skill",
                    description=str(metadata.description or ""),
                    category=str(metadata.category or "skill"),
                    tags=tuple(str(tag) for tag in (metadata.tags or [])),
                    argument_hint=str(metadata.argument_hint or ""),
                )
            )
        return cls(candidates)

    def search(
        self,
        *,
        query: str,
        limit: int,
        current_tools: list[str] | None = None,
        excluded_names: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        query_text = str(query or "").strip()
        query_lower = query_text.lower()
        query_tokens = set(tokenize_discovery_text(query_text))
        excluded = set(current_tools or []) | set(excluded_names or set())
        scored: list[tuple[float, int, ToolDiscoveryCandidate]] = []

        for index, candidate in enumerate(self._candidates):
            if candidate.name in excluded:
                continue
            score = self._score_candidate(
                candidate=candidate,
                query_lower=query_lower,
                query_tokens=query_tokens,
            )
            if score <= 0:
                continue
            scored.append((score, index, candidate))

        scored.sort(key=lambda row: (-row[0], row[1]))
        return [
            {
                "name": candidate.name,
                "type": candidate.kind,
                "source": candidate.source,
                "reason": candidate.description
                or f"{candidate.kind.title()} metadata matched the requested capability.",
                "score": round(score, 3),
                "category": candidate.category or candidate.kind,
            }
            for score, _, candidate in scored[:limit]
        ]

    def _score_candidate(
        self,
        *,
        candidate: ToolDiscoveryCandidate,
        query_lower: str,
        query_tokens: set[str],
    ) -> float:
        haystack = candidate.search_text
        haystack_lower = expand_discovery_text(haystack).lower()
        haystack_tokens = set(tokenize_discovery_text(haystack))
        name_tokens = set(tokenize_discovery_text(candidate.name))
        score = 0.0

        if candidate.name.lower() in query_lower:
            score += 0.7
        if name_tokens and name_tokens.issubset(query_tokens):
            score += 0.5

        overlap = query_tokens & haystack_tokens
        score += min(len(overlap), 6) * 0.12

        category = candidate.category.strip().lower()
        if category and category in query_tokens:
            score += 0.25

        for tag in candidate.tags:
            tag_tokens = set(tokenize_discovery_text(tag))
            if tag_tokens and tag_tokens & query_tokens:
                score += 0.08

        for token in query_tokens:
            if len(token) > 2 and token in haystack_lower:
                score += 0.03

        if candidate.kind == "skill":
            score += self._skill_specific_score(candidate, query_tokens)
        else:
            score += self._tool_specific_score(candidate, query_tokens)
        return score

    @staticmethod
    def _skill_specific_score(
        candidate: ToolDiscoveryCandidate,
        query_tokens: set[str],
    ) -> float:
        score = 0.0
        if candidate.argument_hint:
            hint_tokens = set(tokenize_discovery_text(candidate.argument_hint))
            score += min(len(query_tokens & hint_tokens), 3) * 0.06
        return score

    @staticmethod
    def _tool_specific_score(
        candidate: ToolDiscoveryCandidate,
        query_tokens: set[str],
    ) -> float:
        score = 0.0
        for key, weight in (
            ("task_intents", 0.14),
            ("domains", 0.12),
            ("operations", 0.1),
        ):
            values = candidate.metadata.get(key)
            if not isinstance(values, list):
                continue
            value_tokens = set(
                token
                for value in values
                for token in tokenize_discovery_text(str(value))
            )
            if value_tokens & query_tokens:
                score += weight
        return score


def expand_discovery_text(text: str) -> str:
    lowered = str(text or "").lower()
    aliases: list[str] = []
    for marker, expansions in _DISCOVERY_SYNONYMS:
        if marker in lowered:
            aliases.extend(expansions)
    if not aliases:
        return lowered
    return " ".join([lowered, *aliases])


def tokenize_discovery_text(text: str) -> list[str]:
    expanded = expand_discovery_text(text)
    tokens: list[str] = []
    for match in _TOKEN_RE.findall(expanded):
        token = match.lower().strip()
        if len(token) > 1:
            tokens.append(token)
    return tokens


def _infer_tool_source(*, name: str, category: str, metadata: dict[str, Any]) -> str:
    normalized_category = str(category or "").strip().lower()
    if normalized_category == "mcp" or str(name or "").startswith("mcp__"):
        return "mcp"
    if metadata.get("mcp_server_id"):
        return "mcp"
    if normalized_category == "external":
        return "external"
    return "builtin"


__all__ = [
    "ToolDiscoveryCandidate",
    "ToolDiscoveryIndex",
    "expand_discovery_text",
    "tokenize_discovery_text",
]
