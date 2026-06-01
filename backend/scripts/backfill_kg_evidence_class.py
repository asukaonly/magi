"""One-shot backfill: populate knowledge_graph.evidence_class from L1 fact_events.

Reads each edge's evidence_event_ids, joins L1 fact_events to find the most
authoritative evidence_class, and writes it back. Run after migration
0010_kg_evidence_class.

Usage:
    python backend/scripts/backfill_kg_evidence_class.py <memory_db_path> <l1_db_path>

NULL evidence_class on edges is intentionally non-fatal in Phase 1 — the
filter in Task 6 doesn't exclude NULL, and the reranker in Task 10 uses a
default weight of 0.5. This script is operational cleanup so existing edges
stop riding the NULL-default path.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import aiosqlite

# Priority order (higher = more authoritative).
# Mirrors the plan's priority chain:
# USER_SELF_REPORT > EXTERNAL_OBSERVATION > USER_REPORT_ABOUT_OTHERS >
# ASSISTANT_TOOL_GROUNDED > ASSISTANT_QUOTE > ASSISTANT_FREEFORM >
# ASSISTANT_RUNTIME_DERIVATION > SYSTEM_RUNTIME > USER_QUESTION > USER_REQUEST > UNKNOWN
_AUTHORITY: dict[str, int] = {
    "user_self_report": 10,
    "external_observation": 9,
    "user_report_about_others": 8,
    "assistant_tool_grounded": 5,
    "assistant_quote": 4,
    "assistant_freeform": 3,
    "assistant_runtime_derivation": 2,
    "system_runtime": 1,
    "user_question": 0,
    "user_request": 0,
    "unknown": -1,
}


def _label_for_int(value: int) -> str:
    # Mirror EvidenceClass enum int -> label without importing the module
    # (script may run before package install in fresh deploy). Keep in sync
    # with backend/src/magi/memory/evidence/models.py::EvidenceClass._labels().
    labels = {
        1: "unknown",
        2: "user_self_report",
        3: "user_report_about_others",
        4: "assistant_quote",
        5: "assistant_tool_grounded",
        6: "assistant_freeform",
        7: "assistant_runtime_derivation",
        8: "external_observation",
        9: "system_runtime",
        10: "user_question",
        11: "user_request",
    }
    return labels.get(value, "unknown")


async def backfill(memory_db_path: Path, l1_db_path: Path, batch_size: int = 500) -> None:
    print(f"Backfilling evidence_class on {memory_db_path}")
    async with aiosqlite.connect(memory_db_path) as memdb, aiosqlite.connect(l1_db_path) as l1db:
        memdb.row_factory = aiosqlite.Row
        l1db.row_factory = aiosqlite.Row

        # Build map: event_id -> evidence_class label
        events_map: dict[str, str] = {}
        async with l1db.execute(
            "SELECT event_id, evidence_class FROM fact_events WHERE evidence_class IS NOT NULL"
        ) as cur:
            async for row in cur:
                events_map[row["event_id"]] = _label_for_int(int(row["evidence_class"]))

        async with memdb.execute(
            "SELECT triple_id, evidence_event_ids FROM knowledge_graph WHERE evidence_class IS NULL"
        ) as cur:
            rows = await cur.fetchall()

        updated = 0
        for row in rows:
            ids = json.loads(row["evidence_event_ids"] or "[]")
            classes = [events_map.get(eid) for eid in ids if events_map.get(eid)]
            if not classes:
                continue
            best = max(classes, key=lambda c: _AUTHORITY.get(c, -1))
            await memdb.execute(
                "UPDATE knowledge_graph SET evidence_class = ? WHERE triple_id = ?",
                (best, row["triple_id"]),
            )
            updated += 1
            if updated % batch_size == 0:
                await memdb.commit()
                print(f"  ...{updated} rows backfilled")
        await memdb.commit()
        print(f"Done. Total rows updated: {updated}.")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python backfill_kg_evidence_class.py <memory_db_path> <l1_db_path>")
        sys.exit(1)
    asyncio.run(backfill(Path(sys.argv[1]), Path(sys.argv[2])))
