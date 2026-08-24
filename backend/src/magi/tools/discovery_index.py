"""Unified discovery index for runtime tool and skill recommendations."""

from __future__ import annotations

import math
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
    ("附件", ("attachment", "uploaded", "file", "chat")),
    ("上传", ("uploaded", "attachment", "file")),
    ("发给我", ("attach", "send", "delivery")),
    ("之前", ("memory", "history", "prior", "previous")),
    ("以前", ("memory", "history", "prior", "previous")),
    ("说过", ("memory", "conversation", "said", "recall")),
    ("聊过", ("memory", "conversation", "history", "recall")),
    ("记得", ("memory", "remember", "recall")),
    ("记忆", ("memory", "remember", "recall")),
    ("历史", ("history", "memory", "prior")),
)
_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+", re.IGNORECASE)
_NAME_SPLIT_RE = re.compile(r"[_\-.:/]+")
_METADATA_SEARCH_KEYS = (
    "task_intents",
    "domains",
    "operations",
    "query_shapes",
    "tool_hint",
)
_MEMORY_QUERY_TOKENS = {
    "memory",
    "memories",
    "remember",
    "recall",
    "history",
    "historical",
    "prior",
    "previous",
    "previously",
    "earlier",
    "before",
    "said",
    "conversation",
    "conversations",
}
_PHOTO_QUERY_TOKENS = {"photo", "photos", "image", "images", "picture", "pictures"}
_ATTACHMENT_QUERY_TOKENS = {
    "attachment",
    "attachments",
    "uploaded",
    "upload",
    "file",
    "files",
    "pdf",
    "document",
    "chat",
}


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
    parameters: tuple[dict[str, Any], ...] = ()
    examples: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def search_text(self) -> str:
        """Build the searchable document used by BM25 and future vector indexes."""
        metadata_parts: list[str] = []
        for key in _METADATA_SEARCH_KEYS:
            value = self.metadata.get(key)
            if isinstance(value, list):
                metadata_parts.extend(str(item) for item in value)
            elif isinstance(value, str):
                metadata_parts.append(value)
        parameter_parts: list[str] = []
        for parameter in self.parameters:
            parameter_parts.extend(
                [
                    str(parameter.get("name") or ""),
                    str(parameter.get("description") or ""),
                    str(parameter.get("type") or ""),
                ]
            )
        example_parts = [_compact_search_value(example) for example in self.examples[:3]]
        name_words = _NAME_SPLIT_RE.sub(" ", self.name)
        return " ".join(
            [
                self.name,
                name_words,
                self.name,
                self.kind,
                self.source,
                self.description,
                self.category,
                self.argument_hint,
                self.argument_hint,
                " ".join(self.tags),
                " ".join(self.tags),
                " ".join(parameter_parts),
                " ".join(metadata_parts),
                " ".join(example_parts),
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
                    parameters=_normalize_parameters(info.get("parameters")),
                    examples=_normalize_examples(info.get("examples")),
                    metadata=dict(info.get("metadata") or {}),
                )
            )

        get_skill_names = getattr(registry, "get_skill_names", None)
        get_skill_metadata = getattr(registry, "get_skill_metadata", None)
        skill_names = get_skill_names() if callable(get_skill_names) else []
        for skill_name in skill_names:
            metadata = (
                get_skill_metadata(skill_name)
                if callable(get_skill_metadata)
                else None
            )
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
                    metadata={
                        "domains": [str(metadata.category or "skill")],
                        "tool_hint": str(metadata.context or ""),
                    },
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
        query_token_list = tokenize_discovery_text(query_text)
        query_tokens = set(query_token_list)
        excluded = set(current_tools or []) | set(excluded_names or set())
        corpus = [
            (
                index,
                candidate,
                tokenize_discovery_text(candidate.search_text, include_english_aliases=False),
            )
            for index, candidate in enumerate(self._candidates)
            if candidate.name not in excluded
        ]
        stats = _build_bm25_stats([tokens for _, _, tokens in corpus])
        scored: list[tuple[float, int, ToolDiscoveryCandidate]] = []

        for index, candidate, document_tokens in corpus:
            score = self._score_candidate(
                candidate=candidate,
                query_lower=query_lower,
                query_tokens=query_tokens,
                query_token_list=query_token_list,
                document_tokens=document_tokens,
                bm25_stats=stats,
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
        query_token_list: list[str],
        document_tokens: list[str],
        bm25_stats: "_BM25Stats",
    ) -> float:
        haystack_lower = _expand_discovery_text(
            candidate.search_text,
            include_english_aliases=False,
        ).lower()
        haystack_tokens = set(document_tokens)
        name_tokens = set(tokenize_discovery_text(candidate.name, include_english_aliases=False))
        score = _bm25_score(query_token_list, document_tokens, bm25_stats)

        if candidate.name.lower() in query_lower:
            score += 1.2
        if name_tokens and name_tokens.issubset(query_tokens):
            score += 0.9

        overlap = query_tokens & haystack_tokens
        score += min(len(overlap), 8) * 0.08

        category = candidate.category.strip().lower()
        if category and category in query_tokens:
            score += 0.35

        for tag in candidate.tags:
            tag_tokens = set(tokenize_discovery_text(tag, include_english_aliases=False))
            if tag_tokens and tag_tokens & query_tokens:
                score += 0.14

        for token in query_tokens:
            if len(token) > 2 and token in haystack_lower:
                score += 0.04

        score += self._capability_family_score(
            candidate=candidate,
            query_tokens=query_tokens,
            haystack_tokens=haystack_tokens,
            haystack_lower=haystack_lower,
        )
        if candidate.kind == "skill":
            score += self._skill_specific_score(candidate, query_tokens)
        else:
            score += self._tool_specific_score(candidate, query_tokens)
        return score

    @staticmethod
    def _capability_family_score(
        *,
        candidate: ToolDiscoveryCandidate,
        query_tokens: set[str],
        haystack_tokens: set[str],
        haystack_lower: str,
    ) -> float:
        score = 0.0
        has_memory_query = bool(query_tokens & _MEMORY_QUERY_TOKENS)
        has_memory_doc = (
            candidate.category.strip().lower() == "memory"
            or "memory" in candidate.name.lower()
            or "memory" in haystack_tokens
            or "memories" in haystack_tokens
        )
        if has_memory_query and has_memory_doc:
            score += 2.8

        has_photo_query = bool(query_tokens & _PHOTO_QUERY_TOKENS)
        has_photo_doc = (
            bool(haystack_tokens & _PHOTO_QUERY_TOKENS)
            or "photo" in candidate.name.lower()
        )
        if has_photo_query and has_photo_doc:
            score += 2.4

        has_attachment_query = bool(query_tokens & _ATTACHMENT_QUERY_TOKENS)
        has_attachment_doc = bool(query_tokens & haystack_tokens & _ATTACHMENT_QUERY_TOKENS)
        if has_attachment_query and has_attachment_doc:
            score += 1.4

        if has_photo_query and "read_chat_attachment" == candidate.name:
            score -= 0.8
        return score

    @staticmethod
    def _skill_specific_score(
        candidate: ToolDiscoveryCandidate,
        query_tokens: set[str],
    ) -> float:
        score = 0.0
        if candidate.argument_hint:
            hint_tokens = set(
                tokenize_discovery_text(
                    candidate.argument_hint,
                    include_english_aliases=False,
                )
            )
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
                for token in tokenize_discovery_text(
                    str(value),
                    include_english_aliases=False,
                )
            )
            if value_tokens & query_tokens:
                score += weight
        return score


@dataclass(frozen=True, slots=True)
class _BM25Stats:
    doc_lengths: tuple[int, ...]
    avg_doc_length: float
    doc_frequency: dict[str, int]
    doc_count: int


def _build_bm25_stats(documents: list[list[str]]) -> _BM25Stats:
    doc_lengths = tuple(len(document) for document in documents)
    doc_frequency: dict[str, int] = {}
    for document in documents:
        for token in set(document):
            doc_frequency[token] = doc_frequency.get(token, 0) + 1
    avg_doc_length = sum(doc_lengths) / max(len(doc_lengths), 1)
    return _BM25Stats(
        doc_lengths=doc_lengths,
        avg_doc_length=avg_doc_length,
        doc_frequency=doc_frequency,
        doc_count=len(documents),
    )


def _bm25_score(
    query_tokens: list[str],
    document_tokens: list[str],
    stats: _BM25Stats,
    *,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    if not query_tokens or not document_tokens or stats.doc_count <= 0:
        return 0.0
    term_frequency: dict[str, int] = {}
    for token in document_tokens:
        term_frequency[token] = term_frequency.get(token, 0) + 1

    score = 0.0
    doc_length = len(document_tokens)
    for token in query_tokens:
        df = stats.doc_frequency.get(token, 0)
        tf = term_frequency.get(token, 0)
        if df <= 0 or tf <= 0:
            continue
        idf = math.log(1 + (stats.doc_count - df + 0.5) / (df + 0.5))
        norm = tf * (k1 + 1) / (
            tf + k1 * (1 - b + b * doc_length / max(stats.avg_doc_length, 1.0))
        )
        score += idf * norm
    return score


def expand_discovery_text(text: str) -> str:
    return _expand_discovery_text(text, include_english_aliases=True)


def _expand_discovery_text(text: str, *, include_english_aliases: bool) -> str:
    lowered = str(text or "").lower()
    aliases: list[str] = []
    if include_english_aliases:
        for token, expansions in _ENGLISH_DISCOVERY_SYNONYMS.items():
            if token in lowered:
                aliases.extend(expansions)
    for marker, expansions in _DISCOVERY_SYNONYMS:
        if marker in lowered:
            aliases.extend(expansions)
    if not aliases:
        return lowered
    return " ".join([lowered, *aliases])


def tokenize_discovery_text(text: str, *, include_english_aliases: bool = True) -> list[str]:
    expanded = _expand_discovery_text(
        text,
        include_english_aliases=include_english_aliases,
    )
    tokens: list[str] = []
    for match in _TOKEN_RE.findall(expanded):
        token = match.lower().strip()
        if len(token) > 1:
            tokens.append(token)
    return tokens


_ENGLISH_DISCOVERY_SYNONYMS: dict[str, tuple[str, ...]] = {
    "previously": ("memory", "history", "prior", "recall"),
    "previous": ("memory", "history", "prior", "recall"),
    "earlier": ("memory", "history", "prior", "recall"),
    "before": ("memory", "history", "prior", "recall"),
    "said": ("memory", "conversation", "recall"),
    "remember": ("memory", "recall", "history"),
    "uploaded": ("attachment", "file", "chat"),
    "upload": ("attachment", "file", "chat"),
    "attach": ("attachment", "delivery", "send"),
    "photo": ("image", "picture"),
    "photos": ("image", "picture"),
}


def _normalize_parameters(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        return ()
    parameters: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            parameters.append(dict(item))
    return tuple(parameters)


def _normalize_examples(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        return ()
    examples: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            examples.append(dict(item))
    return tuple(examples)


def _compact_search_value(value: Any, *, max_chars: int = 500) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)[:max_chars]
    if isinstance(value, dict):
        parts: list[str] = []
        for key, item in value.items():
            parts.append(str(key))
            parts.append(_compact_search_value(item, max_chars=max_chars // 2))
        return " ".join(parts)[:max_chars]
    if isinstance(value, list):
        return " ".join(_compact_search_value(item, max_chars=max_chars // 2) for item in value)[
            :max_chars
        ]
    return str(value)[:max_chars]


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
