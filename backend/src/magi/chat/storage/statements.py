"""Explicit native SQL variants used only inside chat persistence adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Dialect = Literal["sqlite", "mysql"]


@dataclass(frozen=True)
class ChatSql:
    """Keep native statements explicit without translating SQL at runtime."""

    sqlite: str
    mysql: str

    def __add__(self, other: str | ChatSql) -> ChatSql:
        return ChatSql(self.sqlite + render_sql(other, "sqlite"), self.mysql + render_sql(other, "mysql"))

    def __radd__(self, other: str | ChatSql) -> ChatSql:
        return ChatSql(render_sql(other, "sqlite") + self.sqlite, render_sql(other, "mysql") + self.mysql)

    def __str__(self) -> str:
        raise TypeError("SQL fragments must be rendered by their storage driver")


def render_sql(value: str | ChatSql, dialect: Dialect) -> str:
    return getattr(value, dialect) if isinstance(value, ChatSql) else value


def statement(sqlite: str, mysql: str | None = None, **fragments: str | ChatSql) -> ChatSql:
    """Compose trusted SQL fragments; user values always remain bound parameters."""
    native = mysql if mysql is not None else sqlite
    if not fragments:
        return ChatSql(sqlite, native)
    return ChatSql(
        sqlite.format(**{name: render_sql(value, "sqlite") for name, value in fragments.items()}),
        native.format(**{name: render_sql(value, "mysql") for name, value in fragments.items()}),
    )


def join_sql(separator: str, fragments: list[str | ChatSql]) -> ChatSql:
    return ChatSql(
        separator.join(render_sql(value, "sqlite") for value in fragments),
        separator.join(render_sql(value, "mysql") for value in fragments),
    )


def mysql_ascii_lower(expression: str) -> str:
    """Match SQLite NOCASE's ASCII-only identity folding without truncating Unicode."""
    for upper, lower in zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz", strict=True):
        expression = f"REPLACE({expression}, '{upper}', '{lower}')"
    return expression
