"""Session + persistent storage for user-authored permission rules.

The store tracks two kinds of rules:

* **Session rules**   — live only in memory; cleared on session reset.
* **Persistent rules** — SQLite-backed at ``permission_rules.db``.

Matching happens against the in-memory caches of both layers; session
rules win over persistent ones when both match.
"""

from __future__ import annotations

import asyncio
import json
import time
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Iterable

import aiosqlite

from ...core.logger import get_logger
from ...core.sqlite import sqlite_connection_async
from .contracts import PermissionRule, PermissionScope

__all__ = ["PermissionRuleStore"]


logger = get_logger(__name__)


_DEFAULT_DB_PATH = "~/.magi/runtime/permission_rules.db"


class PermissionRuleStore:
    """Session + persistent rule cache.

    Sessions are keyed by ``session_id``; pass ``None`` for the
    implicit global session (useful in tests).
    """

    def __init__(self, *, db_path: str | None = _DEFAULT_DB_PATH) -> None:
        self._db_path: str | None = (
            str(Path(db_path).expanduser()) if db_path else None
        )
        self._lock = asyncio.Lock()
        self._session_rules: dict[str | None, dict[str, PermissionRule]] = {}
        self._persistent_rules: dict[str, PermissionRule] = {}
        self._initialized = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        if self._initialized:
            return
        if self._db_path:
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            await self._reload_persistent()
        self._initialized = True

    async def close(self) -> None:
        # Nothing persistent is held open; per-call connections already
        # closed by ``sqlite_connection_async``.
        self._initialized = False

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    async def add(
        self,
        rule: PermissionRule,
        *,
        session_id: str | None = None,
    ) -> PermissionRule:
        """Insert a rule at the scope it declares and return it."""
        if rule.scope is PermissionScope.ONE_SHOT:
            raise ValueError("one-shot rules are never persisted")

        async with self._lock:
            if rule.scope is PermissionScope.SESSION:
                bucket = self._session_rules.setdefault(session_id, {})
                bucket[rule.rule_id] = rule
                return rule

            # Persistent.
            if not self._db_path:
                self._persistent_rules[rule.rule_id] = rule
                return rule

            async with sqlite_connection_async(
                self._db_path, profile="hot_write"
            ) as db:
                await db.execute(
                    """
                    INSERT OR REPLACE INTO permission_rules
                        (rule_id, tool_name, scope, matcher_json, allow, note, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rule.rule_id,
                        rule.tool_name,
                        rule.scope.value,
                        json.dumps(rule.matcher, ensure_ascii=False),
                        int(bool(rule.allow)),
                        rule.note,
                        float(rule.created_at),
                    ),
                )
                await db.commit()
            self._persistent_rules[rule.rule_id] = rule
            return rule

    async def remove(self, rule_id: str, *, session_id: str | None = None) -> bool:
        """Delete a rule by id from wherever it lives. Returns ``True`` on hit."""
        async with self._lock:
            session_bucket = self._session_rules.get(session_id)
            if session_bucket and rule_id in session_bucket:
                session_bucket.pop(rule_id, None)
                return True
            removed_persistent = self._persistent_rules.pop(rule_id, None) is not None
            if removed_persistent and self._db_path:
                async with sqlite_connection_async(
                    self._db_path, profile="hot_write"
                ) as db:
                    await db.execute(
                        "DELETE FROM permission_rules WHERE rule_id = ?",
                        (rule_id,),
                    )
                    await db.commit()
            return removed_persistent

    async def clear_session(self, session_id: str | None) -> None:
        """Drop every session-scoped rule for ``session_id``."""
        async with self._lock:
            self._session_rules.pop(session_id, None)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def list_rules(
        self,
        *,
        session_id: str | None = None,
        include_persistent: bool = True,
    ) -> list[PermissionRule]:
        rules: list[PermissionRule] = []
        session_bucket = self._session_rules.get(session_id)
        if session_bucket:
            rules.extend(session_bucket.values())
        if include_persistent:
            rules.extend(self._persistent_rules.values())
        return rules

    def find_match(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        session_id: str | None = None,
    ) -> PermissionRule | None:
        """Return the first matching rule, preferring session scope."""
        session_bucket = self._session_rules.get(session_id)
        if session_bucket:
            match = _first_match(
                session_bucket.values(),
                tool_name=tool_name,
                arguments=arguments,
            )
            if match is not None:
                return match
        return _first_match(
            self._persistent_rules.values(),
            tool_name=tool_name,
            arguments=arguments,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _reload_persistent(self) -> None:
        if not self._db_path:
            return
        loaded: dict[str, PermissionRule] = {}
        async with sqlite_connection_async(self._db_path, profile="readonly") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT rule_id, tool_name, scope, matcher_json, allow, note, created_at "
                "FROM permission_rules"
            ) as cursor:
                async for row in cursor:
                    try:
                        rule = PermissionRule(
                            rule_id=row["rule_id"],
                            tool_name=row["tool_name"],
                            scope=PermissionScope(row["scope"]),
                            matcher=json.loads(row["matcher_json"]),
                            allow=bool(row["allow"]),
                            note=row["note"],
                            created_at=float(row["created_at"] or time.time()),
                        )
                        loaded[rule.rule_id] = rule
                    except Exception as exc:  # skip corrupt rows rather than fail boot
                        logger.warning(
                            "permission_rule.load_error",
                            rule_id=row["rule_id"],
                            error=str(exc),
                        )
        self._persistent_rules = loaded


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def _first_match(
    rules: Iterable[PermissionRule],
    *,
    tool_name: str,
    arguments: dict[str, Any],
) -> PermissionRule | None:
    for rule in rules:
        if rule.tool_name != tool_name:
            continue
        if _rule_matches(rule, arguments):
            return rule
    return None


def _rule_matches(rule: PermissionRule, arguments: dict[str, Any]) -> bool:
    if rule.scope in {PermissionScope.SESSION, PermissionScope.PERSISTENT_EXACT}:
        # Exact: every declared key must equal the live value.
        for key, expected in rule.matcher.items():
            if arguments.get(key) != expected:
                return False
        return True
    if rule.scope is PermissionScope.PERSISTENT_PATTERN:
        for key, pattern in rule.matcher.items():
            value = arguments.get(key)
            if not isinstance(pattern, str) or not isinstance(value, str):
                # Patterns only apply to string values.
                if value != pattern:
                    return False
                continue
            if not fnmatchcase(value, pattern):
                return False
        return True
    return False
