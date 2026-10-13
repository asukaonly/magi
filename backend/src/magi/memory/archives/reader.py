"""Stream historical archives through live correction and forgetting governance."""

from __future__ import annotations

from collections import Counter
from contextlib import asynccontextmanager
import heapq
import json
from pathlib import Path
import re
from typing import AsyncIterator

import aiosqlite

from ..evidence import L1RetrievalScope
from ..source_event_governance import business_source_references, chat_session_source_reference
from .models import ArchiveRecord, ArchiveSearchIssue, ArchiveSearchResult

_ARCHIVE_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}\.db$")
_PAGE_SIZE = 64
_MAX_PAYLOAD_BYTES = 4 * 1024 * 1024


class ArchiveGovernanceUnavailable(RuntimeError):
    """The current governance snapshot could not authorize historical disclosure."""


@asynccontextmanager
async def _readonly(path: Path) -> AsyncIterator[aiosqlite.Connection]:
    async with aiosqlite.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA query_only = ON")
        yield db


class ArchiveReader:
    """Search original retained text without rehydrating any active memory layer."""

    def __init__(self, *, archive_dir: Path, memory_db_path: str | Path) -> None:
        self._archive_dir = Path(archive_dir)
        self._memory_db_path = Path(memory_db_path)

    async def search(
        self,
        *,
        query: str = "",
        limit: int = 20,
        offset: int = 0,
        event_ids: tuple[str, ...] | None = None,
    ) -> ArchiveSearchResult:
        if not 1 <= limit <= 100 or not 0 <= offset <= 10000:
            raise ValueError("Archive pagination is out of bounds")
        if event_ids is not None and (
            not 1 <= len(event_ids) <= 100
            or any(not isinstance(event_id, str) or not 1 <= len(event_id) <= 512 for event_id in event_ids)
        ):
            raise ValueError("Archive event filters are out of bounds")
        normalized_event_ids = tuple(dict.fromkeys(event_ids)) if event_ids is not None else None
        normalized_query = query.casefold().strip()
        issues: Counter[str] = Counter()
        retained: list[tuple[float, str, str, ArchiveRecord]] = []
        seen: set[tuple[str, str]] = set()
        total = 0
        try:
            async with _readonly(self._memory_db_path) as governance:
                await governance.execute("BEGIN")
                # Validate the complete read policy even when there are no archives.
                await _blocked_references(governance, ())
                ranges = await _forget_ranges(governance)
                try:
                    paths = sorted(
                        (path for path in self._archive_dir.iterdir() if path.suffix == ".db"),
                        reverse=True,
                    )
                except FileNotFoundError:
                    paths = []
                except OSError:
                    paths = []
                    issues["archive_unreadable"] += 1
                root = self._archive_dir.resolve()
                for path in paths:
                    if (
                        not _ARCHIVE_NAME.fullmatch(path.name)
                        or path.is_symlink()
                        or not path.is_file()
                        or path.resolve().parent != root
                    ):
                        issues["archive_unsafe"] += 1
                        continue
                    try:
                        async with _readonly(path) as archive:
                            async with archive.execute(
                                "SELECT name FROM sqlite_master WHERE type = 'table'"
                            ) as cursor:
                                tables = {str(row[0]) for row in await cursor.fetchall()}
                            if not tables.intersection(
                                {"archived_l1_events", "archived_l3_summaries"}
                            ):
                                issues["archive_unreadable"] += 1
                                continue
                            for layer, table, key in (
                                ("l1", "archived_l1_events", "event_id"),
                                ("l3", "archived_l3_summaries", "summary_id"),
                            ):
                                if table not in tables or (normalized_event_ids is not None and layer != "l1"):
                                    continue
                                event_filter = (
                                    f" WHERE {key} IN (SELECT value FROM json_each(?))"
                                    if normalized_event_ids is not None else ""
                                )
                                async with archive.execute(
                                    f"SELECT {key}, archived_at, CASE WHEN length(payload_json) <= ? "
                                    f"THEN payload_json ELSE NULL END AS payload_json FROM {table}{event_filter}",
                                    (_MAX_PAYLOAD_BYTES, json.dumps(normalized_event_ids))
                                    if normalized_event_ids is not None else (_MAX_PAYLOAD_BYTES,),
                                ) as cursor:
                                    while rows := await cursor.fetchmany(_PAGE_SIZE):
                                        candidates: list[tuple[ArchiveRecord, tuple[str, ...]]] = []
                                        for row in rows:
                                            identity = (layer, str(row[key]))
                                            if identity in seen:
                                                continue
                                            seen.add(identity)
                                            try:
                                                parsed = _record(layer, row, key)
                                            except (ValueError, TypeError, KeyError, OverflowError):
                                                issues["record_invalid"] += 1
                                                continue
                                            if parsed is None:
                                                continue
                                            item, references = parsed
                                            if (
                                                normalized_query
                                                and normalized_query not in item.content.casefold()
                                            ):
                                                continue
                                            if any(
                                                start <= (item.period_end or item.occurred_at)
                                                and end >= item.occurred_at
                                                for start, end in ranges
                                            ):
                                                continue
                                            candidates.append((item, references))
                                        try:
                                            blocked = await _blocked_references(
                                                governance,
                                                tuple(
                                                    ref for _, refs in candidates for ref in refs
                                                ),
                                            )
                                        except (aiosqlite.Error, OSError) as exc:
                                            raise ArchiveGovernanceUnavailable(
                                                "Archive governance is unavailable"
                                            ) from exc
                                        for item, references in candidates:
                                            if "*" in blocked or blocked.intersection(references):
                                                continue
                                            total += 1
                                            entry = (
                                                item.occurred_at,
                                                item.layer,
                                                item.record_id,
                                                item,
                                            )
                                            if len(retained) < offset + limit:
                                                heapq.heappush(retained, entry)
                                            elif entry[:3] > retained[0][:3]:
                                                heapq.heapreplace(retained, entry)
                    except (aiosqlite.Error, OSError):
                        issues["archive_unreadable"] += 1
                await governance.rollback()
        except ArchiveGovernanceUnavailable:
            raise
        except (aiosqlite.Error, OSError) as exc:
            raise ArchiveGovernanceUnavailable("Archive governance is unavailable") from exc
        ordered = sorted(retained, key=lambda row: row[:3], reverse=True)
        return ArchiveSearchResult(
            items=[row[3] for row in ordered[offset : offset + limit]],
            total=total,
            limit=limit,
            offset=offset,
            partial=bool(issues),
            issues=[
                ArchiveSearchIssue(code=code, count=count) for code, count in sorted(issues.items())
            ],
        )


async def _blocked_references(db: aiosqlite.Connection, references: tuple[str, ...]) -> set[str]:
    """Apply source, claim and correction barriers in one authoritative snapshot."""
    candidates = json.dumps(sorted(set(references) | {"*"}))
    async with db.execute(
        """SELECT event_id FROM memory_source_event_tombstones
        WHERE event_id IN (SELECT value FROM json_each(?))
        UNION SELECT event_id FROM memory_projection_blocks
        WHERE event_id IN (SELECT value FROM json_each(?))
        UNION SELECT event_id FROM memory_forget_evidence_events
        WHERE event_id IN (SELECT value FROM json_each(?))
        UNION SELECT evidence.event_id FROM memory_correction_evidence_events evidence
        JOIN memory_corrections correction ON correction.correction_id = evidence.correction_id
        WHERE correction.state = 'active' AND correction.transition_cancelled_at IS NULL
          AND evidence.event_id IN (SELECT value FROM json_each(?))
        UNION SELECT '*' FROM memory_correction_evidence_fail_closed closed
        JOIN memory_corrections correction ON correction.correction_id = closed.correction_id
        WHERE correction.state = 'active' AND correction.transition_cancelled_at IS NULL
        UNION SELECT '*' FROM memory_forget_claim_rules WHERE evidence_fail_closed = 1""",
        (candidates, candidates, candidates, candidates),
    ) as cursor:
        return {str(row[0]) for row in await cursor.fetchall()}


async def _forget_ranges(db: aiosqlite.Connection) -> list[tuple[float, float]]:
    async with db.execute(
        "SELECT range_start, range_end FROM memory_time_range_forget_barriers"
    ) as cursor:
        return [(float(row[0]), float(row[1])) for row in await cursor.fetchall()]


def _record(
    layer: str, row: aiosqlite.Row, key: str
) -> tuple[ArchiveRecord, tuple[str, ...]] | None:
    payload = json.loads(row["payload_json"])
    if not isinstance(payload, dict):
        raise ValueError("Archive record must be an object")
    record_id = str(row[key])
    if layer == "l1":
        if payload["event_id"] != record_id:
            raise ValueError("Archive identity mismatch")
        if (
            L1RetrievalScope.from_value(payload["l1_retrieval_scope"])
            is L1RetrievalScope.AUDIT_ONLY
        ):
            return None
        references = [record_id]
        if payload.get("turn_id"):
            references.append(str(payload["turn_id"]))
        if payload.get("user_id") and payload.get("session_id"):
            references.append(
                chat_session_source_reference(
                    user_id=str(payload["user_id"]),
                    session_id=str(payload["session_id"]),
                )
            )
        references.extend(
            business_source_references(
                source=str(payload["source"]),
                event_type=str(payload["event_type"]),
                source_item_id=payload.get("source_item_id"),
                idempotency_key=payload.get("idempotency_key"),
            )
        )
        item = ArchiveRecord(
            record_id=record_id,
            layer="l1",
            content=payload["content"],
            source=payload["source"],
            event_type=payload["event_type"],
            occurred_at=payload["timestamp"],
            archived_at=row["archived_at"],
            evidence_event_ids=[record_id],
        )
        return item, tuple(references)
    summary = payload["summary"]
    if not isinstance(summary, dict) or summary["summary_id"] != record_id:
        raise ValueError("Archive summary identity mismatch")
    event_ids = summary["source_event_ids"]
    if not isinstance(event_ids, list) or any(
        not isinstance(item, str) or not item for item in event_ids
    ):
        raise ValueError("Archive summary evidence is invalid")
    links = payload["event_links"]
    if not isinstance(links, list) or any(
        not isinstance(link, dict) or not link.get("event_id") for link in links
    ):
        raise ValueError("Archive summary evidence links are invalid")
    references = tuple(dict.fromkeys(event_ids + [str(link["event_id"]) for link in links]))
    if not references:
        raise ValueError("Archive summary has no traceable evidence")
    item = ArchiveRecord(
        record_id=record_id,
        layer="l3",
        content=summary["content"],
        source="memory_summary",
        event_type=summary["summary_type"],
        occurred_at=summary["period_start"],
        period_end=summary["period_end"],
        archived_at=row["archived_at"],
        evidence_event_ids=list(references),
    )
    if item.period_end is None or item.period_end < item.occurred_at:
        raise ValueError("Archive summary period is invalid")
    return item, references
