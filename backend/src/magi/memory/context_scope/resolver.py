"""Deterministic local resolver for retrieval context signals."""

from __future__ import annotations

import asyncio
import re
import time

from .catalog import ContextCatalog
from .cache_epoch import context_cache_epoch
from .identity import claimed_workspace_identity, normalize_alias
from .models import (
    ContextCondition,
    ContextDimension,
    ContextResolutionSignals,
    normalize_context_scope,
)


class ContextScopeResolver:
    """Resolve trusted workspace and conservative alias signals without an LLM."""

    def __init__(self, db_path: str) -> None:
        self._catalog = ContextCatalog(db_path)
        self._cache_epoch = context_cache_epoch(db_path)
        self._workspace_context_cache: dict[str, str] = {}
        self._workspace_cache_lock = asyncio.Lock()
        self._alias_cache: (
            tuple[
                float,
                dict[ContextDimension, list[tuple[str, str]]],
            ]
            | None
        ) = None
        self._alias_cache_lock = asyncio.Lock()

    @property
    def catalog(self) -> ContextCatalog:
        return self._catalog

    async def resolve(
        self,
        signals: ContextResolutionSignals | None,
    ) -> dict[str, list[dict[str, str]]]:
        """Resolve a context scope, omitting ambiguous dimensions."""
        self._refresh_after_catalog_change()
        if signals is None or signals.is_empty:
            return {}

        workspace_context_id: str | None = None
        workspace_path = str(signals.workspace_path or "").strip()
        if workspace_path:
            try:
                workspace_context_id = await self._workspace_context_id(workspace_path)
            except (OSError, RuntimeError, ValueError):
                workspace_context_id = None

        conditions: list[ContextCondition] = []
        text = str(signals.user_text or "")
        aliases = await self._alias_index()
        project_mentions = self._resolve_text_dimension(
            aliases["project"],
            text,
        )
        if workspace_context_id is not None:
            conditions.append(ContextCondition("project", workspace_context_id))
        elif len(project_mentions) == 1:
            conditions.append(ContextCondition("project", next(iter(project_mentions))))

        for dimension in ("activity", "place", "person"):
            mentioned = self._resolve_text_dimension(aliases[dimension], text)
            if len(mentioned) == 1:
                conditions.append(
                    ContextCondition(dimension, next(iter(mentioned)))  # type: ignore[arg-type]
                )

        if not any(item.dimension == "activity" for item in conditions):
            normalized_task_category = normalize_alias(signals.task_category)
            activity = list(
                dict.fromkeys(
                    context_id
                    for alias, context_id in aliases["activity"]
                    if alias == normalized_task_category
                )
            )
            if len(activity) == 1:
                conditions.append(ContextCondition("activity", activity[0]))

        if not conditions:
            return {}
        return normalize_context_scope(
            {"all_of": [condition.to_dict() for condition in conditions]}
        )

    def _refresh_after_catalog_change(self) -> None:
        current_epoch = context_cache_epoch(self._catalog.db_path)
        if current_epoch == self._cache_epoch:
            return
        self._workspace_context_cache.clear()
        self._alias_cache = None
        self._cache_epoch = current_epoch

    async def _workspace_context_id(self, workspace_path: str) -> str | None:
        identity = claimed_workspace_identity(workspace_path)
        if identity is None:
            return None
        binding_id, _ = identity
        cached = self._workspace_context_cache.get(binding_id)
        if cached is not None:
            return cached
        async with self._workspace_cache_lock:
            cached = self._workspace_context_cache.get(binding_id)
            if cached is not None:
                return cached
            workspace = await self._catalog.register_workspace(workspace_path)
            if workspace is None:
                return None
            self._workspace_context_cache[workspace.binding_id] = workspace.context_id
            self._alias_cache = None
            self._cache_epoch = context_cache_epoch(self._catalog.db_path)
            return workspace.context_id

    async def _alias_index(
        self,
    ) -> dict[ContextDimension, list[tuple[str, str]]]:
        cached = self._alias_cache
        now = time.monotonic()
        if cached is not None and now - cached[0] <= 30.0:
            return cached[1]
        async with self._alias_cache_lock:
            cached = self._alias_cache
            now = time.monotonic()
            if cached is not None and now - cached[0] <= 30.0:
                return cached[1]
            aliases = await self._catalog.list_aliases_by_dimension()
            self._alias_cache = (now, aliases)
            return aliases

    @staticmethod
    def _resolve_text_dimension(
        aliases: list[tuple[str, str]],
        text: str,
    ) -> set[str]:
        normalized_text = normalize_alias(text)
        if not normalized_text:
            return set()
        matched: set[str] = set()
        for alias, context_id in aliases:
            if _alias_is_mentioned(normalized_text, alias):
                matched.add(context_id)
        return matched


def _alias_is_mentioned(text: str, alias: str) -> bool:
    """Match explicit aliases while avoiding substrings inside Latin words."""
    if len(alias) < 2:
        return text == alias
    if re.fullmatch(r"[a-z0-9][a-z0-9 ._\-/]*", alias):
        return re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", text) is not None
    return alias in text


__all__ = ["ContextScopeResolver"]
