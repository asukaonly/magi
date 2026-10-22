"""MySQL ngram full-text retrieval, always filtered by current source facts."""

from __future__ import annotations

import re

from sqlalchemy import and_, func, literal, or_, select, update
from sqlalchemy.dialects.mysql import match

from ...ports import EventQuery
from ...retrieval.search_text import get_search_text
from .common import record
from .queries import filters
from . import schema as s


class MysqlEventLexical:
    async def bm25_search(
        self,
        query: str,
        *,
        limit: int = 20,
        user_id: str | None = None,
        start_time: float | None = None,
        end_time: float | None = None,
        strict: bool = False,
        l1_retrieval_scopes: list[str] | None = None,
    ) -> list[tuple[str, float]]:
        words = list(dict.fromkeys(re.findall(r"[^\W_]+", query.casefold())))
        if not words or l1_retrieval_scopes == []:
            return []
        conditions = filters(
            EventQuery(
                user_id=user_id,
                start_time=start_time,
                end_time=end_time,
                l1_retrieval_scopes=l1_retrieval_scopes,
            )
        )
        async with self._transaction() as connection:
            for required in [True] if strict else [True, False]:
                indexed = [word for word in words if len(word) >= 2]
                short = [word for word in words if len(word) < 2]
                query_text = " ".join(
                    ("+" if required else "") + '"' + word + '"' for word in indexed
                )
                score = (
                    match(s.events.c.search_text, against=query_text).in_boolean_mode()
                    if indexed
                    else literal(1.0)
                )
                matches = [score > 0] if indexed else []
                matches.extend(
                    func.lower(s.events.c.search_text).contains(word, autoescape=True)
                    for word in short
                )
                constraint = and_(*matches) if required else or_(*matches)
                exact = []
                if strict:
                    exact = [
                        func.regexp_like(
                            s.events.c.search_text,
                            r"(^|[^[:alnum:]_])" + re.escape(word) + r"([^[:alnum:]_]|$)",
                            "i",
                        )
                        for word in words
                        if word.isascii()
                    ]
                rows = await connection.execute(
                    select(s.events.c.event_id, score.label("score"))
                    .where(
                        *conditions,
                        constraint,
                        *exact,
                    )
                    .order_by(score.desc(), s.events.c.id)
                    .limit(max(1, int(limit)))
                )
                results = [(str(row.event_id), -float(row.score)) for row in rows]
                if results:
                    return results
        return []

    async def backfill_fts(self, *, batch_size: int = 500) -> int:
        """Repair missing search text from active sources under the write fence."""
        after, count = 0, 0
        through = await self.event_scan_high_water()
        while True:
            async with self._transaction(write=True) as connection:
                rows = (
                    (
                        await connection.execute(
                            select(s.events)
                            .where(
                                s.events.c.id > after,
                                s.events.c.id <= through,
                                s.events.c.deleted_at.is_(None),
                                s.events.c.search_text == "",
                            )
                            .order_by(s.events.c.id)
                            .limit(max(1, batch_size))
                        )
                    )
                    .mappings()
                    .all()
                )
                if not rows:
                    break
                for row in rows:
                    await connection.execute(
                        update(s.events)
                        .where(s.events.c.id == row["id"])
                        .values(search_text=get_search_text(record(row).event))
                    )
                    after = int(row["id"])
                    count += 1
        return count
