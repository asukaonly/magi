"""Offline governance stats over L1 fact_events (dev-time observability).

Headline signal: ``user_default`` fallback hit-rate among classified rows — a
high value means many real inputs fall through to the catch-all rule, i.e. the
classifier has a coverage gap (the #49 failure mode), surfaced from the real
distribution instead of a user's eyes.

Usage:
    python backend/scripts/evidence_stats.py [l1_db_path]
Default db: ~/.magi/data/memory/l1_events.db
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import aiosqlite

from magi.memory.evidence import EvidenceClass, EvidenceStatus, L1RetrievalScope

_DEFAULT_DB = "~/.magi/data/memory/l1_events.db"


async def compute_evidence_stats(db_path: str) -> dict:
    counts_class: dict[str, int] = {}
    counts_scope: dict[str, int] = {}
    counts_reason: dict[str, int] = {}
    total = 0
    classified = 0
    errors = 0

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT evidence_status, evidence_class, l1_retrieval_scope, metadata_json "
            "FROM fact_events"
        ) as cur:
            async for row in cur:
                total += 1
                status = EvidenceStatus.from_value(row["evidence_status"]).label
                cls = EvidenceClass.from_value(row["evidence_class"]).label
                scope = L1RetrievalScope.from_value(row["l1_retrieval_scope"]).label
                counts_class[cls] = counts_class.get(cls, 0) + 1
                counts_scope[scope] = counts_scope.get(scope, 0) + 1
                if status in ("classification_error", "policy_error"):
                    errors += 1
                elif status == "classified":
                    classified += 1
                # else: UNKNOWN / not-yet-classified — counted in total only,
                # excluded from both classified and errors so the hit-rate
                # denominator reflects only genuinely classified rows.
                reason = None
                if row["metadata_json"]:
                    try:
                        meta = json.loads(row["metadata_json"])
                        reason = (meta.get("_evidence") or {}).get("reason_code")
                    except (json.JSONDecodeError, AttributeError):
                        reason = None
                if reason:
                    counts_reason[reason] = counts_reason.get(reason, 0) + 1

    default_hits = counts_reason.get("user_default", 0)
    return {
        "total": total,
        "classified": classified,
        "errors": errors,
        "error_rate": (errors / total) if total else 0.0,
        "evidence_class": counts_class,
        "l1_retrieval_scope": counts_scope,
        "reason_code": counts_reason,
        "user_default_hit_rate": (default_hits / classified) if classified else 0.0,
    }


def _format_report(stats: dict) -> str:
    lines = [
        f"total={stats['total']}  classified={stats['classified']}  "
        f"errors={stats['errors']} ({stats['error_rate']:.1%})",
        f"user_default hit-rate (among classified): {stats['user_default_hit_rate']:.1%}",
        "evidence_class:",
    ]
    for k, v in sorted(stats["evidence_class"].items(), key=lambda kv: -kv[1]):
        lines.append(f"  {k:<28} {v}")
    lines.append("reason_code:")
    for k, v in sorted(stats["reason_code"].items(), key=lambda kv: -kv[1]):
        lines.append(f"  {k:<28} {v}")
    lines.append("l1_retrieval_scope:")
    for k, v in sorted(stats["l1_retrieval_scope"].items(), key=lambda kv: -kv[1]):
        lines.append(f"  {k:<28} {v}")
    return "\n".join(lines)


async def _main() -> None:
    raw = sys.argv[1] if len(sys.argv) > 1 else _DEFAULT_DB
    db_path = str(Path(raw).expanduser())
    stats = await compute_evidence_stats(db_path)
    print(_format_report(stats))


if __name__ == "__main__":
    asyncio.run(_main())
