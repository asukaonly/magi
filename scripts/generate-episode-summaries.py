#!/usr/bin/env python3
"""Batch-generate LLM summaries for episodes that lack one.

Reads candidate/active episodes from L2, loads their member events from L1,
then calls the core LLM to produce a short summary and label for each episode.
Updates the episode record and FTS index in-place.

Usage:
    python scripts/generate-episode-summaries.py                  # default
    python scripts/generate-episode-summaries.py --concurrency 5  # parallel
    python scripts/generate-episode-summaries.py --dry-run        # preview only
    python scripts/generate-episode-summaries.py --limit 100      # cap count
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_SRC_DIR = ROOT_DIR / "backend" / "src"
if str(BACKEND_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC_DIR))

import aiosqlite  # noqa: E402
from magi.config import get_config  # noqa: E402
from magi.core.sqlite import sqlite_connection_async  # noqa: E402
from magi.llm.factory import create_scenario_llm_pool, create_core_llm_adapter  # noqa: E402
from magi.memory.l1.event_store import L1EventStore  # noqa: E402
from magi.memory.l2.store import L2CognitionStore  # noqa: E402
from magi.utils.runtime import get_runtime_paths, set_runtime_dir  # noqa: E402

# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a memory system that writes concise episode summaries.
An episode is a cluster of temporally and thematically related events from the user's life.
Your job is to read the events and produce:
1. A short **label** (≤10 words) that names the episode.
2. A **summary** (2-5 sentences) that captures what happened, who was involved, and key outcomes.

IMPORTANT: Respond ONLY with a single-line JSON object. No markdown, no code fences, no extra text.
Format: {"label": "...", "summary": "..."}
Use the same language as the events. Do not invent information not present in the events.
Keep the summary concise to fit in one JSON line."""

USER_PROMPT_TEMPLATE = """\
Episode time range: {time_start} — {time_end}
Entity context: {entities}
Event count: {event_count}

Events (oldest first):
{events_text}"""

MAX_EVENTS_PER_PROMPT = 30
MAX_CONTENT_CHARS = 400

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ts_to_str(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def _truncate(text: str, limit: int = MAX_CONTENT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


async def _load_events_bulk(
    l1_db_path: str, event_ids: List[str]
) -> List[Dict[str, Any]]:
    """Load multiple L1 events by ID in a single query."""
    if not event_ids:
        return []
    async with sqlite_connection_async(l1_db_path, profile="hot_write") as db:
        db.row_factory = aiosqlite.Row
        placeholders = ",".join("?" for _ in event_ids)
        sql = (
            f"SELECT event_id, content, event_type, author_type, timestamp, session_id "
            f"FROM fact_events WHERE event_id IN ({placeholders}) AND deleted_at IS NULL "
            f"ORDER BY timestamp ASC"
        )
        async with db.execute(sql, tuple(event_ids)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


def _build_events_text(events: List[Dict[str, Any]]) -> str:
    """Format events into a compact text block for the LLM prompt."""
    # Sample if too many events
    if len(events) > MAX_EVENTS_PER_PROMPT:
        step = len(events) / MAX_EVENTS_PER_PROMPT
        indices = [int(i * step) for i in range(MAX_EVENTS_PER_PROMPT)]
        sampled = [events[i] for i in indices]
    else:
        sampled = events

    lines = []
    for ev in sampled:
        ts = _ts_to_str(ev["timestamp"])
        author = ev.get("author_type") or "system"
        content = _truncate(ev.get("content") or "(empty)")
        lines.append(f"[{ts}] ({author}) {content}")
    return "\n".join(lines)


def _parse_llm_response(raw: str) -> Dict[str, str]:
    """Extract label + summary from LLM JSON response."""
    raw = raw.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

    # Try direct parse first
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Try to extract JSON object from the text
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(raw[start:end])
        else:
            raise

    return {
        "label": str(data.get("label", "")).strip()[:200],
        "summary": str(data.get("summary", "")).strip()[:2000],
    }


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


async def _generate_summary_for_episode(
    episode: Dict[str, Any],
    l1_db_path: str,
    l2_store: L2CognitionStore,
    llm,
    dry_run: bool,
) -> bool:
    """Generate and persist summary for a single episode. Returns True on success."""
    episode_id = episode["episode_id"]

    # 1. Load member event IDs
    memberships = await l2_store.list_episode_events(
        episode_id=episode_id, limit=1000
    )
    event_ids = [m["event_id"] for m in memberships]
    if not event_ids:
        return False

    # 2. Bulk-load events from L1
    events = await _load_events_bulk(l1_db_path, event_ids)
    if not events:
        return False

    # 3. Build prompt
    entities = ", ".join(episode.get("primary_entity_ids") or [])
    user_prompt = USER_PROMPT_TEMPLATE.format(
        time_start=_ts_to_str(episode["time_start"]),
        time_end=_ts_to_str(episode["time_end"]),
        entities=entities or "(none)",
        event_count=len(events),
        events_text=_build_events_text(events),
    )

    if dry_run:
        print(f"  [dry-run] {episode_id}: {len(events)} events, "
              f"{_ts_to_str(episode['time_start'])} — {_ts_to_str(episode['time_end'])}")
        return True

    # 4. Call LLM
    raw = await llm.generate(
        user_prompt,
        system_prompt=SYSTEM_PROMPT,
        temperature=0.3,
        max_tokens=500,
    )

    # 5. Parse
    try:
        result = _parse_llm_response(raw)
    except (json.JSONDecodeError, KeyError) as exc:
        print(f"  ✗ {episode_id}: parse error: {exc}")
        return False

    if not result["summary"]:
        print(f"  ✗ {episode_id}: empty summary")
        return False

    # 6. Persist
    await l2_store.update_episode(
        episode_id=episode_id,
        summary=result["summary"],
        label=result["label"],
        status="active",
    )
    await l2_store.index_episode_fts(
        episode_id=episode_id,
        summary=result["summary"],
        label=result["label"],
        user_label=episode.get("user_label") or "",
    )
    return True


async def _generate_summary_with_retry(
    episode: Dict[str, Any],
    l1_db_path: str,
    l2_store: L2CognitionStore,
    llm,
    max_retries: int = 3,
) -> tuple:
    """Retry wrapper that backs off on 429 / transient errors."""
    retried = 0
    for attempt in range(max_retries + 1):
        try:
            ok = await _generate_summary_for_episode(
                episode, l1_db_path, l2_store, llm, dry_run=False
            )
            return (ok, retried)
        except Exception as exc:
            err_str = str(exc)
            if "429" in err_str or "rate" in err_str.lower():
                retried += 1
                wait = 2 ** attempt + 1
                await asyncio.sleep(wait)
                continue
            # Non-retryable error
            print(f"  ✗ {episode['episode_id']}: {exc}")
            return (False, retried)
    print(f"  ✗ {episode['episode_id']}: max retries exhausted")
    return (False, retried)


async def _run() -> int:
    args = _parse_args()
    if args.base_dir:
        set_runtime_dir(args.base_dir)

    runtime_paths = get_runtime_paths()
    config = get_config()

    l1_db_path = str(runtime_paths.l1_memory_db_path)
    l2_db_path = str(runtime_paths.memory_db_path)

    # Stores
    l1_store = L1EventStore(db_path=l1_db_path, vector_enabled=False, async_embeddings=False)
    await l1_store.initialize()
    l2_store = L2CognitionStore(db_path=l2_db_path)
    await l2_store.initialize()

    # LLM
    if not args.dry_run:
        pool = create_scenario_llm_pool(config)
        llm = create_core_llm_adapter(pool)
        print(f"LLM:       core scenario adapter ready")
    else:
        llm = None

    # Count episodes needing summaries
    print(f"L1 db:     {l1_db_path}")
    print(f"L2 db:     {l2_db_path}")

    # Query episodes without summaries
    all_episodes: List[Dict[str, Any]] = []
    offset = 0
    page_size = 500
    while True:
        page = await l2_store.list_episodes(
            statuses=["candidate", "active"],
            limit=page_size,
            offset=offset,
        )
        if not page:
            break
        for ep in page:
            if not ep.get("summary"):
                all_episodes.append(ep)
        offset += page_size
        if len(page) < page_size:
            break

    total = len(all_episodes)
    if args.limit and args.limit < total:
        all_episodes = all_episodes[:args.limit]
        total = len(all_episodes)

    print(f"Episodes without summary: {total}")
    if total == 0:
        print("Nothing to do.")
        return 0

    if args.dry_run:
        print(f"\n[dry-run] Would generate summaries for {total} episodes.")
        for ep in all_episodes[:10]:
            await _generate_summary_for_episode(ep, l1_db_path, l2_store, llm, True)
        if total > 10:
            print(f"  ... and {total - 10} more")
        return 0

    # Process in sequential batches with rate limiting
    batch_size = args.concurrency
    delay_between_batches = args.delay
    success = 0
    failed = 0
    retries_total = 0
    t0 = time.time()

    for batch_start in range(0, total, batch_size):
        batch = all_episodes[batch_start : batch_start + batch_size]

        results = await asyncio.gather(
            *[
                _generate_summary_with_retry(
                    ep, l1_db_path, l2_store, llm, max_retries=3
                )
                for ep in batch
            ],
            return_exceptions=True,
        )

        for ep, result in zip(batch, results):
            if isinstance(result, Exception):
                failed += 1
                print(f"  ✗ {ep['episode_id']}: {result}")
            elif result is True:
                success += 1
            elif result is False:
                failed += 1
            else:
                # Tuple (ok, retry_count) from retry wrapper
                ok, retried = result
                retries_total += retried
                if ok:
                    success += 1
                else:
                    failed += 1

        done = success + failed
        elapsed = time.time() - t0
        rate = done / elapsed if elapsed > 0 else 0
        print(f"  {done}/{total} ({done*100//total}%)  "
              f"{rate:.1f} ep/s  ok={success} fail={failed}")

        # Rate-limit: sleep between batches
        if batch_start + batch_size < total:
            await asyncio.sleep(delay_between_batches)

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s")
    print(f"  Success:  {success}")
    print(f"  Failed:   {failed}")
    print(f"  Rate:     {success/elapsed:.1f} ep/s" if elapsed > 0 else "")

    return 0 if failed == 0 else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch-generate LLM summaries for episodes."
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="Max parallel LLM calls per batch (default: 3).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Seconds to wait between batches (default: 1.0).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max number of episodes to process.",
    )
    parser.add_argument(
        "--base-dir",
        type=str,
        default=None,
        help="Override runtime base directory (~/.magi).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview without calling LLM or writing.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
