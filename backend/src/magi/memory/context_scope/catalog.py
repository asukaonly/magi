"""SQLite-backed catalog for stable local context identities."""

from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from typing import Any

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from .cache_epoch import invalidate_context_caches
from .identity import (
    canonical_workspace_path,
    claimed_workspace_identity,
    normalize_alias,
)
from .models import (
    ContextDimension,
    ContextOption,
    ContextScopeError,
    context_conditions,
    normalize_context_scope,
)

_INTERNAL_CONTEXT_ID_RE = re.compile(r"^ctx_(project|activity|place|person|time)_[0-9a-f]{64}$")


async def clear_user_contexts(db: aiosqlite.Connection) -> None:
    """Delete user-derived contexts while preserving code-defined aliases."""
    await db.execute(
        """
        DELETE FROM memory_context_aliases
        WHERE context_id IN (
            SELECT context_id FROM memory_context_catalog
            WHERE source_kind != 'built_in'
        )
        """
    )
    await db.execute("DELETE FROM memory_context_bindings")
    await db.execute("DELETE FROM memory_context_catalog WHERE source_kind != 'built_in'")


def _workspace_records(
    workspace_paths: list[str],
    *,
    existing_only: bool,
) -> list[tuple[str, str, str, str]]:
    candidates: dict[str, tuple[bool, str, str, str]] = {}
    for workspace_path in workspace_paths:
        raw_path = str(workspace_path or "").strip()
        if not raw_path:
            continue
        try:
            canonical_path = canonical_workspace_path(raw_path)
            is_directory = Path(canonical_path).is_dir()
            identity = claimed_workspace_identity(raw_path)
        except (OSError, RuntimeError, ValueError):
            continue
        if existing_only and not is_directory:
            continue
        if identity is None:
            continue
        binding_id, context_id = identity
        label = Path(canonical_path).name.strip() or "Workspace"
        candidate = (
            is_directory,
            canonical_path,
            context_id,
            label,
        )
        existing = candidates.get(binding_id)
        if existing is None or _prefer_workspace_candidate(candidate, existing):
            candidates[binding_id] = candidate
    return [
        (context_id, binding_id, label, canonical_path)
        for binding_id, (_, canonical_path, context_id, label) in candidates.items()
    ]


def _prefer_workspace_candidate(
    candidate: tuple[bool, str, str, str],
    existing: tuple[bool, str, str, str],
) -> bool:
    if candidate[0] != existing[0]:
        return candidate[0]
    return candidate[1] < existing[1]


def _with_disambiguated_labels(
    options: list[ContextOption],
    records: list[tuple[str, str, str, str]],
) -> list[ContextOption]:
    path_by_binding = {binding_id: path for _, binding_id, _, path in records}
    groups: dict[str, list[ContextOption]] = {}
    for option in options:
        groups.setdefault(normalize_alias(option.label), []).append(option)

    display_labels = {option.context_id: option.label for option in options}
    for group in groups.values():
        if len(group) <= 1:
            continue
        unresolved = list(group)
        used: set[str] = set()
        for parent_depth in (1, 2):
            candidates = {
                option.context_id: _relative_workspace_label(
                    path_by_binding[option.binding_id],
                    parent_depth=parent_depth,
                )
                for option in unresolved
            }
            counts: dict[str, int] = {}
            for candidate in candidates.values():
                normalized = normalize_alias(candidate)
                counts[normalized] = counts.get(normalized, 0) + 1
            next_unresolved: list[ContextOption] = []
            for option in unresolved:
                candidate = candidates[option.context_id]
                normalized = normalize_alias(candidate)
                if counts[normalized] == 1 and normalized not in used:
                    display_labels[option.context_id] = candidate
                    used.add(normalized)
                else:
                    next_unresolved.append(option)
            unresolved = next_unresolved
            if not unresolved:
                break
        for index, option in enumerate(
            sorted(
                unresolved,
                key=lambda item: path_by_binding[item.binding_id],
            )
        ):
            base = _relative_workspace_label(
                path_by_binding[option.binding_id],
                parent_depth=2,
            )
            display_labels[option.context_id] = f"{base} · {_display_sequence(index)}"

    return sorted(
        (
            ContextOption(
                context_id=option.context_id,
                dimension=option.dimension,
                label=display_labels[option.context_id],
                binding_kind=option.binding_kind,
                binding_id=option.binding_id,
            )
            for option in options
        ),
        key=lambda option: (normalize_alias(option.label), option.context_id),
    )


def _relative_workspace_label(path: str, *, parent_depth: int) -> str:
    current = Path(path)
    parts = [current.name or "Workspace"]
    parent = current.parent
    for _ in range(parent_depth):
        if parent == parent.parent:
            break
        if parent.name:
            parts.insert(0, parent.name)
        parent = parent.parent
    return "/".join(parts)


def _display_sequence(index: int) -> str:
    quotient, remainder = divmod(index, 26)
    letter = chr(ord("A") + remainder)
    return letter if quotient == 0 else f"{letter}{quotient + 1}"


class ContextCatalog:
    """Persist context labels, aliases, and trusted local bindings."""

    def __init__(self, db_path: str) -> None:
        self.db_path = str(db_path)

    async def register_workspace(self, workspace_path: str) -> ContextOption | None:
        """Register or refresh one workspace-bound project context."""
        options = await self.register_workspaces([workspace_path])
        return options[0] if options else None

    async def register_workspaces(
        self,
        workspace_paths: list[str],
    ) -> list[ContextOption]:
        """Register workspaces in one transaction, de-duplicated by binding id."""
        records = await asyncio.to_thread(
            _workspace_records,
            workspace_paths,
            existing_only=False,
        )
        if not records:
            return []
        return await self._write_workspace_records(records, deactivate_missing=False)

    async def sync_workspace_project_options(
        self,
        workspace_paths: list[str],
    ) -> list[ContextOption]:
        """Synchronize selectable projects from every current chat workspace."""
        records = await asyncio.to_thread(
            _workspace_records,
            workspace_paths,
            existing_only=True,
        )
        options = await self._write_workspace_records(
            records,
            deactivate_missing=True,
        )
        return options

    async def _write_workspace_records(
        self,
        records: list[tuple[str, str, str, str]],
        *,
        deactivate_missing: bool,
    ) -> list[ContextOption]:
        now = time.time()
        options: list[ContextOption] = []
        changed = False
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                for default_context_id, binding_id, label, _ in records:
                    context_id = await self._select_workspace_context_id(
                        db,
                        binding_id=binding_id,
                        default_context_id=default_context_id,
                    )
                    changed = (
                        await self._upsert_workspace(
                            db,
                            context_id=context_id,
                            binding_id=binding_id,
                            label=label,
                            now=now,
                        )
                        or changed
                    )
                    options.append(
                        ContextOption(
                            context_id=context_id,
                            dimension="project",
                            label=label,
                            binding_kind="workspace",
                            binding_id=binding_id,
                        )
                    )
                if deactivate_missing:
                    changed = (
                        await self._deactivate_missing_workspace_options(
                            db,
                            active_context_ids=[item.context_id for item in options],
                            now=now,
                        )
                        or changed
                    )
                display_options = (
                    _with_disambiguated_labels(options, records) if deactivate_missing else options
                )
                if deactivate_missing:
                    for option in display_options:
                        cursor = await db.execute(
                            """
                            UPDATE memory_context_catalog
                            SET display_label = ?, updated_at = ?
                            WHERE context_id = ?
                              AND COALESCE(display_label, label) != ?
                            """,
                            (
                                option.label,
                                now,
                                option.context_id,
                                option.label,
                            ),
                        )
                        changed = cursor.rowcount > 0 or changed
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        if changed:
            invalidate_context_caches(self.db_path)
        return display_options

    @staticmethod
    async def _deactivate_missing_workspace_options(
        db: aiosqlite.Connection,
        *,
        active_context_ids: list[str],
        now: float,
    ) -> bool:
        if active_context_ids:
            placeholders = ",".join("?" for _ in active_context_ids)
            cursor = await db.execute(
                f"""
                UPDATE memory_context_catalog
                SET is_active = 0, updated_at = ?
                WHERE dimension = 'project' AND source_kind = 'workspace'
                  AND is_active != 0
                  AND context_id NOT IN ({placeholders})
                """,
                (now, *active_context_ids),
            )
            return cursor.rowcount > 0
        cursor = await db.execute(
            """
            UPDATE memory_context_catalog
            SET is_active = 0, updated_at = ?
            WHERE dimension = 'project' AND source_kind = 'workspace'
              AND is_active != 0
            """,
            (now,),
        )
        return cursor.rowcount > 0

    @classmethod
    async def _upsert_workspace(
        cls,
        db: aiosqlite.Connection,
        *,
        context_id: str,
        binding_id: str,
        label: str,
        now: float,
    ) -> bool:
        changed = False
        cursor = await db.execute(
            """
            INSERT INTO memory_context_catalog(
                context_id, dimension, label, display_label, source_kind, is_active,
                created_at, updated_at
            ) VALUES (?, 'project', ?, ?, 'workspace', 1, ?, ?)
            ON CONFLICT(context_id) DO UPDATE SET
                label = excluded.label,
                source_kind = 'workspace',
                is_active = 1,
                updated_at = excluded.updated_at
            WHERE memory_context_catalog.label != excluded.label
               OR memory_context_catalog.source_kind != 'workspace'
               OR memory_context_catalog.is_active != 1
            """,
            (context_id, label, label, now, now),
        )
        changed = cursor.rowcount > 0
        cursor = await db.execute(
            """
            INSERT INTO memory_context_bindings(
                context_id, binding_kind, binding_id, created_at
            ) VALUES (?, 'workspace', ?, ?)
            ON CONFLICT(binding_kind, binding_id) DO UPDATE SET
                context_id = excluded.context_id
            WHERE memory_context_bindings.context_id != excluded.context_id
            """,
            (context_id, binding_id, now),
        )
        changed = cursor.rowcount > 0 or changed
        changed = (
            await cls._upsert_alias(
                db,
                context_id=context_id,
                alias=label,
                created_at=now,
            )
            or changed
        )
        return changed

    @staticmethod
    async def _select_workspace_context_id(
        db: aiosqlite.Connection,
        *,
        binding_id: str,
        default_context_id: str,
    ) -> str:
        async with db.execute(
            """
            SELECT context_id
            FROM memory_context_bindings
            WHERE binding_kind = 'workspace' AND binding_id = ?
            """,
            (binding_id,),
        ) as cursor:
            bound = await cursor.fetchone()
        if bound is not None:
            return str(bound[0])
        return default_context_id

    async def list_workspace_project_options(self) -> list[ContextOption]:
        """Return only active workspace-bound projects exposed in product UI."""
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT catalog.context_id, catalog.dimension,
                       COALESCE(catalog.display_label, catalog.label) AS label,
                       bindings.binding_kind, bindings.binding_id
                FROM memory_context_catalog AS catalog
                JOIN memory_context_bindings AS bindings
                  ON bindings.context_id = catalog.context_id
                 AND bindings.binding_kind = 'workspace'
                WHERE catalog.dimension = 'project'
                  AND catalog.source_kind = 'workspace'
                  AND catalog.is_active = 1
                ORDER BY catalog.label COLLATE NOCASE, catalog.context_id
                """
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._option_from_row(row) for row in rows]

    async def get_context_labels(self, context_ids: set[str]) -> dict[str, str]:
        """Load labels for referenced contexts, including inactive records."""
        normalized_ids = sorted(
            {str(context_id).strip() for context_id in context_ids if str(context_id).strip()}
        )
        if not normalized_ids:
            return {}
        labels: dict[str, str] = {}
        async with sqlite_connection_async(self.db_path) as db:
            for offset in range(0, len(normalized_ids), 500):
                chunk = normalized_ids[offset : offset + 500]
                placeholders = ",".join("?" for _ in chunk)
                async with db.execute(
                    f"""
                    SELECT context_id, COALESCE(display_label, label) AS label
                    FROM memory_context_catalog
                    WHERE context_id IN ({placeholders})
                    """,
                    tuple(chunk),
                ) as cursor:
                    rows = await cursor.fetchall()
                for context_id, raw_label in rows:
                    label = str(raw_label or "").strip()
                    if (
                        not label
                        or label == str(context_id)
                        or _INTERNAL_CONTEXT_ID_RE.fullmatch(label)
                    ):
                        continue
                    labels[str(context_id)] = label
        return labels

    async def get_context(self, context_id: str) -> dict[str, Any] | None:
        """Load one active context and its optional binding."""
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT catalog.context_id, catalog.dimension, catalog.label,
                       catalog.source_kind, catalog.is_active,
                       bindings.binding_kind, bindings.binding_id
                FROM memory_context_catalog AS catalog
                LEFT JOIN memory_context_bindings AS bindings
                  ON bindings.context_id = catalog.context_id
                WHERE catalog.context_id = ?
                ORDER BY bindings.binding_kind
                LIMIT 1
                """,
                (str(context_id),),
            ) as cursor:
                row = await cursor.fetchone()
        return dict(row) if row is not None else None

    async def validate_correction_scope(
        self,
        scope: dict[str, Any] | None,
    ) -> dict[str, list[dict[str, str]]]:
        """Validate the ordinary-user correction scope against available projects."""
        normalized = normalize_context_scope(scope)
        if not normalized:
            return {}
        conditions = context_conditions(normalized)
        if len(conditions) != 1 or conditions[0].dimension != "project":
            raise ContextScopeError(
                "Only one workspace-bound project can be selected",
                code="context_scope_not_workspace_bound",
            )
        condition = conditions[0]
        record = await self.get_context(condition.context_id)
        if record is None or not bool(record.get("is_active")):
            raise ContextScopeError(
                "The selected context is not available",
                code="context_scope_unknown",
            )
        if str(record.get("dimension")) != condition.dimension:
            raise ContextScopeError(
                "The selected context has a different dimension",
                code="context_scope_dimension_mismatch",
            )
        if (
            str(record.get("source_kind")) != "workspace"
            or str(record.get("binding_kind")) != "workspace"
            or not str(record.get("binding_id") or "").strip()
        ):
            raise ContextScopeError(
                "The selected project is not bound to a workspace",
                code="context_scope_not_workspace_bound",
            )
        return normalized

    async def find_exact_alias(
        self,
        *,
        dimension: ContextDimension,
        alias: str,
    ) -> list[str]:
        """Return every active identity with the exact normalized alias."""
        normalized = normalize_alias(alias)
        if not normalized:
            return []
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                """
                SELECT aliases.context_id
                FROM memory_context_aliases AS aliases
                JOIN memory_context_catalog AS catalog
                  ON catalog.context_id = aliases.context_id
                WHERE aliases.normalized_alias = ?
                  AND catalog.dimension = ?
                  AND catalog.is_active = 1
                ORDER BY aliases.context_id
                """,
                (normalized, dimension),
            ) as cursor:
                rows = await cursor.fetchall()
        return list(dict.fromkeys(str(row[0]) for row in rows))

    async def list_aliases(
        self,
        *,
        dimension: ContextDimension,
    ) -> list[tuple[str, str]]:
        """Return active aliases for conservative local text matching."""
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                """
                SELECT aliases.normalized_alias, aliases.context_id
                FROM memory_context_aliases AS aliases
                JOIN memory_context_catalog AS catalog
                  ON catalog.context_id = aliases.context_id
                WHERE catalog.dimension = ?
                  AND catalog.is_active = 1
                ORDER BY LENGTH(aliases.normalized_alias) DESC,
                         aliases.normalized_alias,
                         aliases.context_id
                """,
                (dimension,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [(str(row[0]), str(row[1])) for row in rows]

    async def list_aliases_by_dimension(
        self,
    ) -> dict[ContextDimension, list[tuple[str, str]]]:
        """Load the active alias index in one read transaction."""
        result: dict[ContextDimension, list[tuple[str, str]]] = {
            "project": [],
            "activity": [],
            "place": [],
            "person": [],
            "time": [],
        }
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                """
                SELECT catalog.dimension, aliases.normalized_alias,
                       aliases.context_id
                FROM memory_context_aliases AS aliases
                JOIN memory_context_catalog AS catalog
                  ON catalog.context_id = aliases.context_id
                WHERE catalog.is_active = 1
                  AND catalog.dimension IN ('project', 'activity', 'place', 'person')
                ORDER BY catalog.dimension,
                         LENGTH(aliases.normalized_alias) DESC,
                         aliases.normalized_alias,
                         aliases.context_id
                """
            ) as cursor:
                rows = await cursor.fetchall()
        for dimension, alias, context_id in rows:
            result[str(dimension)].append(  # type: ignore[index]
                (str(alias), str(context_id))
            )
        return result

    @staticmethod
    async def _upsert_alias(
        db: aiosqlite.Connection,
        *,
        context_id: str,
        alias: str,
        created_at: float,
    ) -> bool:
        normalized = normalize_alias(alias)
        if not normalized:
            return False
        cursor = await db.execute(
            """
            INSERT INTO memory_context_aliases(
                context_id, normalized_alias, alias, created_at
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(context_id, normalized_alias) DO UPDATE SET
                alias = excluded.alias
            WHERE memory_context_aliases.alias != excluded.alias
            """,
            (context_id, normalized, str(alias).strip(), created_at),
        )
        return cursor.rowcount > 0

    @staticmethod
    def _option_from_row(row: aiosqlite.Row) -> ContextOption:
        return ContextOption(
            context_id=str(row["context_id"]),
            dimension=str(row["dimension"]),  # type: ignore[arg-type]
            label=str(row["label"]),
            binding_kind=str(row["binding_kind"]),
            binding_id=str(row["binding_id"]),
        )


__all__ = ["ContextCatalog", "clear_user_contexts"]
