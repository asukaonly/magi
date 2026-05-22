"""Operational backfill: replace missing / hash-like canonical_names in entity_catalog.

Round 5 I4. After Round 4's render-time slug fallback, a hash-like entity
renders as "(未命名 organization)" instead of leaking the raw hash. This
script upgrades those rows IN-PLACE when a better name can be derived
from existing data:

  Priority sources for a new canonical_name:
    1. Highest-confidence row in `entity_aliases` (alias_text)
    2. Most-frequent row in `entity_mentions` (mention_text)
    3. The slug part of `entity_id` when it's already human-readable
       (covered by Round 4 at render-time; the script does NOT rewrite
       these so we don't conflate "no catalog data" with "trusted name")

Defensive on every dimension: missing tables / columns / DB → skip; never
overwrites a non-hash-like canonical_name; refuses to write a candidate
that is itself hash-like.

Usage::

    # Dry-run report (default) — prints what WOULD change, writes nothing.
    python backend/scripts/backfill_entity_canonical_names.py <memory_db_path>

    # Apply the changes.
    python backend/scripts/backfill_entity_canonical_names.py <memory_db_path> --apply

Idempotent: re-running after --apply is a no-op for already-fixed rows.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional


# Self-contained hash-likeness check — mirrors backend/src/magi/memory/entity_display.py
# so the script can run before the package is importable (fresh deploy).
_MIN_HASH_LENGTH = 8
_HASH_RATIO_THRESHOLD = 0.8
_HEX_CHARS = frozenset("0123456789abcdef")


def _is_hash_like(slug: str) -> bool:
    if not slug or len(slug) < _MIN_HASH_LENGTH:
        return False
    hex_count = sum(1 for c in slug if c in _HEX_CHARS)
    return (hex_count / len(slug)) >= _HASH_RATIO_THRESHOLD


def _needs_backfill(entity_id: str, canonical_name: Optional[str]) -> bool:
    """A row needs backfill when its canonical_name is missing OR equals the
    hash-like part of entity_id (i.e. it was populated from the id itself).
    """
    if not canonical_name:
        return True
    if _is_hash_like(canonical_name):
        return True
    # canonical_name often defaults to the slug part of entity_id; if that
    # slug is hash-like, treat as needing backfill.
    if ":" in entity_id:
        _, _, slug = entity_id.partition(":")
        if canonical_name == slug and _is_hash_like(slug):
            return True
    return False


def _candidates_from_aliases(conn: sqlite3.Connection) -> dict[str, str]:
    """Map entity_id → best alias_text (highest confidence, hash-like skipped)."""
    out: dict[str, str] = {}
    try:
        cur = conn.execute(
            "SELECT entity_id, alias_text, confidence FROM entity_aliases "
            "ORDER BY confidence DESC, alias_id ASC"
        )
    except sqlite3.OperationalError:
        return out
    for entity_id, alias_text, _conf in cur.fetchall():
        text = (alias_text or "").strip()
        if not text or _is_hash_like(text):
            continue
        # First hit wins — ORDER BY confidence DESC sorts the best to top.
        out.setdefault(entity_id, text)
    return out


def _candidates_from_mentions(conn: sqlite3.Connection) -> dict[str, str]:
    """Map entity_id → most-frequent mention_text (hash-like skipped)."""
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    try:
        cur = conn.execute(
            "SELECT resolved_entity_id, mention_text FROM entity_mentions "
            "WHERE resolved_entity_id IS NOT NULL"
        )
    except sqlite3.OperationalError:
        return {}
    for entity_id, mention_text in cur.fetchall():
        text = (mention_text or "").strip()
        if not text or _is_hash_like(text):
            continue
        counts[entity_id][text] += 1
    out: dict[str, str] = {}
    for entity_id, by_text in counts.items():
        # Most-frequent surface; ties broken alphabetically for determinism.
        out[entity_id] = max(by_text.items(), key=lambda kv: (kv[1], -ord(kv[0][0]) if kv[0] else 0))[0]
    return out


def plan_backfill(memory_db_path: Path) -> tuple[list[tuple[str, str, str, str]], dict[str, int]]:
    """Returns (updates, stats) where updates is a list of
    (entity_id, old_name, new_name, source) and stats summarizes the run."""
    updates: list[tuple[str, str, str, str]] = []
    stats: dict[str, int] = defaultdict(int)
    with sqlite3.connect(memory_db_path) as conn:
        try:
            rows = conn.execute(
                "SELECT entity_id, canonical_name FROM entity_catalog"
            ).fetchall()
        except sqlite3.OperationalError:
            print(f"[skip] entity_catalog table missing in {memory_db_path}")
            return [], {}

        alias_map = _candidates_from_aliases(conn)
        mention_map = _candidates_from_mentions(conn)

    for entity_id, canonical_name in rows:
        stats["total"] += 1
        if not _needs_backfill(entity_id, canonical_name):
            stats["already_good"] += 1
            continue
        stats["needs_backfill"] += 1

        candidate = alias_map.get(entity_id)
        source = "alias"
        if not candidate:
            candidate = mention_map.get(entity_id)
            source = "mention"
        if not candidate:
            stats["no_candidate"] += 1
            continue
        if _is_hash_like(candidate):
            # Belt-and-suspenders: the per-source filters already drop these.
            stats["candidate_was_hash"] += 1
            continue
        if candidate == canonical_name:
            stats["already_good"] += 1
            continue

        updates.append((entity_id, canonical_name or "", candidate, source))
        stats["plan_update"] += 1

    return updates, dict(stats)


def apply_backfill(memory_db_path: Path, updates: list[tuple[str, str, str, str]]) -> int:
    """Returns the count of rows actually written."""
    if not updates:
        return 0
    now = time.time()
    with sqlite3.connect(memory_db_path) as conn:
        conn.executemany(
            "UPDATE entity_catalog SET canonical_name = ?, updated_at = ? WHERE entity_id = ?",
            [(new, now, entity_id) for (entity_id, _old, new, _source) in updates],
        )
        conn.commit()
    return len(updates)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("memory_db_path", type=Path)
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry-run)")
    parser.add_argument("--limit", type=int, default=20, help="Sample size to print in the report")
    args = parser.parse_args()

    if not args.memory_db_path.exists():
        print(f"DB not found: {args.memory_db_path}", file=sys.stderr)
        return 1

    updates, stats = plan_backfill(args.memory_db_path)

    print(f"=== entity_catalog canonical_name backfill plan ===")
    print(f"  DB                 : {args.memory_db_path}")
    print(f"  rows examined      : {stats.get('total', 0)}")
    print(f"  already good       : {stats.get('already_good', 0)}")
    print(f"  needs backfill     : {stats.get('needs_backfill', 0)}")
    print(f"    no candidate     : {stats.get('no_candidate', 0)}")
    print(f"    candidate hashy  : {stats.get('candidate_was_hash', 0)}")
    print(f"    plan to update   : {stats.get('plan_update', 0)}")
    print()
    if updates:
        print(f"--- sample of up to {args.limit} planned updates ---")
        for entity_id, old, new, source in updates[: args.limit]:
            shown_old = old or "(NULL)"
            print(f"  [{source}] {entity_id}  '{shown_old}'  →  '{new}'")
        if len(updates) > args.limit:
            print(f"  ... and {len(updates) - args.limit} more")
        print()

    if args.apply:
        written = apply_backfill(args.memory_db_path, updates)
        print(f"APPLIED: wrote {written} rows to {args.memory_db_path}")
    else:
        print("DRY-RUN: pass --apply to write the changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
