"""Runtime-to-memory identity resolution helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import aiosqlite


IDENTITY_LINK_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS identity_links (
    namespace TEXT NOT NULL,
    runtime_user_id TEXT NOT NULL,
    memory_owner_id TEXT NOT NULL,
    link_type TEXT NOT NULL DEFAULT 'runtime_account',
    created_at REAL NOT NULL DEFAULT (strftime('%s', 'now')),
    updated_at REAL NOT NULL DEFAULT (strftime('%s', 'now')),
    PRIMARY KEY (namespace, runtime_user_id)
);
"""


@dataclass(frozen=True, slots=True)
class IdentityLink:
    """Maps a runtime account identity to a canonical memory owner id."""

    namespace: str
    runtime_user_id: str
    memory_owner_id: str
    link_type: str = "runtime_account"


class IdentityResolver:
    """Resolves transport-facing runtime ids to canonical memory owner ids."""

    def __init__(
        self,
        *,
        links: Iterable[IdentityLink] | None = None,
        db_path: str | None = None,
        default_memory_owner_id: str = "user:self",
    ) -> None:
        self._db_path = str(Path(db_path).expanduser()) if db_path else None
        self._links = self._normalize_links(links or [])
        self._default_memory_owner_id = default_memory_owner_id.strip() or "user:self"
        self._db: aiosqlite.Connection | None = None

    @property
    def default_memory_owner_id(self) -> str:
        """Return the fallback canonical memory owner id."""

        return self._default_memory_owner_id

    @classmethod
    def in_memory_default(
        cls,
        *,
        links: Iterable[tuple[str, str, str]] | None = None,
        default_memory_owner_id: str = "user:self",
    ) -> "IdentityResolver":
        """Create an in-memory resolver for single-user execution paths."""

        normalized_links = [
            IdentityLink(namespace=namespace, runtime_user_id=runtime_user_id, memory_owner_id=memory_owner_id)
            for namespace, runtime_user_id, memory_owner_id in (links or [])
        ]
        return cls(links=normalized_links, default_memory_owner_id=default_memory_owner_id)

    async def initialize(self) -> None:
        """Prepare resolver state."""

        if self._db_path is None or self._db is not None:
            return
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute(IDENTITY_LINK_TABLE_SCHEMA)
        await self._db.commit()
        self._links = await self._load_links()

    async def shutdown(self) -> None:
        """Release resolver state."""

        if self._db is None:
            return
        await self._db.close()
        self._db = None

    def resolve_memory_owner_id(self, *, runtime_user_id: str | None, source: str | None) -> str:
        """Resolve the canonical memory owner for a runtime identity."""

        normalized_runtime_user_id = str(runtime_user_id or "").strip()
        normalized_source = str(source or "").strip().casefold()
        if normalized_runtime_user_id:
            linked = self._links.get((normalized_source, normalized_runtime_user_id))
            if linked:
                return linked
        return self._default_memory_owner_id

    async def upsert_identity_link(
        self,
        *,
        namespace: str,
        runtime_user_id: str,
        memory_owner_id: str,
        link_type: str = "runtime_account",
    ) -> IdentityLink:
        """Persist a runtime-to-memory identity link and refresh the cache."""

        link = self._normalize_link(
            IdentityLink(
                namespace=namespace,
                runtime_user_id=runtime_user_id,
                memory_owner_id=memory_owner_id,
                link_type=link_type,
            )
        )
        if link is None:
            raise ValueError("Identity link requires namespace, runtime_user_id, and memory_owner_id")

        if self._db is not None:
            await self._db.execute(
                """
                INSERT INTO identity_links (namespace, runtime_user_id, memory_owner_id, link_type)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(namespace, runtime_user_id) DO UPDATE SET
                    memory_owner_id = excluded.memory_owner_id,
                    link_type = excluded.link_type,
                    updated_at = strftime('%s', 'now')
                """,
                (link.namespace, link.runtime_user_id, link.memory_owner_id, link.link_type),
            )
            await self._db.commit()

        self._links[(link.namespace, link.runtime_user_id)] = link.memory_owner_id
        return link

    async def list_identity_links(self) -> list[IdentityLink]:
        """Return all known runtime-to-memory identity links."""

        if self._db is None:
            return self._cache_links()
        rows = await self._db.execute_fetchall(
            """
            SELECT namespace, runtime_user_id, memory_owner_id, link_type
            FROM identity_links
            ORDER BY namespace, runtime_user_id
            """
        )
        return [
            IdentityLink(
                namespace=str(row[0]),
                runtime_user_id=str(row[1]),
                memory_owner_id=str(row[2]),
                link_type=str(row[3]),
            )
            for row in rows
        ]

    async def _load_links(self) -> dict[tuple[str, str], str]:
        if self._db is None:
            return dict(self._links)
        rows = await self._db.execute_fetchall(
            "SELECT namespace, runtime_user_id, memory_owner_id FROM identity_links"
        )
        return self._normalize_links(
            IdentityLink(namespace=str(row[0]), runtime_user_id=str(row[1]), memory_owner_id=str(row[2]))
            for row in rows
        )

    @staticmethod
    def _normalize_link(link: IdentityLink) -> IdentityLink | None:
        namespace = link.namespace.strip().casefold()
        runtime_user_id = link.runtime_user_id.strip()
        memory_owner_id = link.memory_owner_id.strip()
        link_type = link.link_type.strip() or "runtime_account"
        if not namespace or not runtime_user_id or not memory_owner_id:
            return None
        return IdentityLink(
            namespace=namespace,
            runtime_user_id=runtime_user_id,
            memory_owner_id=memory_owner_id,
            link_type=link_type,
        )

    @classmethod
    def _normalize_links(cls, links: Iterable[IdentityLink]) -> dict[tuple[str, str], str]:
        normalized: dict[tuple[str, str], str] = {}
        for link in links:
            canonical = cls._normalize_link(link)
            if canonical is None:
                continue
            normalized[(canonical.namespace, canonical.runtime_user_id)] = canonical.memory_owner_id
        return normalized

    def _cache_links(self) -> list[IdentityLink]:
        return [
            IdentityLink(namespace=namespace, runtime_user_id=runtime_user_id, memory_owner_id=memory_owner_id)
            for (namespace, runtime_user_id), memory_owner_id in sorted(self._links.items())
        ]


__all__ = ["IdentityLink", "IdentityResolver"]
