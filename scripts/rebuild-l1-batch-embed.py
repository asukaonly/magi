#!/usr/bin/env python3
"""Rebuild L1 embeddings via DashScope Batch File API (50% cost).

Workflow
--------
    prepare  → chunk events, generate JSONL request files + manifest
    submit   → upload files to DashScope, create batch jobs
    status   → poll batch job progress  (add --wait to block)
    import   → download results, build vector cache, write to L1 DB

Usage
-----
    python scripts/rebuild-l1-batch-embed.py prepare
    python scripts/rebuild-l1-batch-embed.py submit
    python scripts/rebuild-l1-batch-embed.py status --wait
    python scripts/rebuild-l1-batch-embed.py import [--batch-size 200]

Work directory: ~/.magi/batch_embed_work/
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sqlite3
import struct
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_SRC_DIR = ROOT_DIR / "backend" / "src"
if str(BACKEND_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC_DIR))

# ── Constants ───────────────────────────────────────────────────

EMBEDDING_MODEL = "text-embedding-v4"
EMBEDDING_DIM = 1024
MAX_TEXTS_PER_REQUEST = 10  # DashScope Batch API limit for embeddings
MAX_REQUESTS_PER_FILE = 50_000
WORK_DIR_NAME = "batch_embed_work"


# ── Helpers ─────────────────────────────────────────────────────

def _work_dir() -> Path:
    d = Path("~/.magi").expanduser() / WORK_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_path() -> Path:
    return _work_dir() / "state.json"


def _load_state() -> dict:
    p = _state_path()
    if p.exists():
        return json.loads(p.read_text())
    return {}


def _save_state(state: dict) -> None:
    _state_path().write_text(json.dumps(state, indent=2, ensure_ascii=False))


def _fmt(secs: float) -> str:
    m, s = divmod(int(secs), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    return f"{m}m{s:02d}s" if m else f"{s}s"


def _get_openai_client():
    """Build OpenAI client from magi LLM config."""
    import yaml
    from openai import OpenAI

    llm_path = Path("~/.magi/config/llm.yaml").expanduser()
    with open(llm_path) as f:
        cfg = yaml.safe_load(f)

    sel = cfg["selections"]["embedding"]
    provider = cfg["providers"][sel["provider_id"]]
    return OpenAI(
        api_key=provider["api_key"],
        base_url=provider["base_url"],
    )


# ── prepare ─────────────────────────────────────────────────────

def cmd_prepare(_args) -> int:
    """Read all L1 events, sentence-chunk, and generate batch JSONL files."""
    from magi.memory.embedding.chunking import chunk_sentences
    from magi.utils.runtime import get_runtime_paths

    paths = get_runtime_paths()
    db_path = str(paths.l1_memory_db_path)
    work = _work_dir()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    total = conn.execute(
        "SELECT count(*) FROM fact_events WHERE deleted_at IS NULL",
    ).fetchone()[0]
    print(f"Database   : {db_path}")
    print(f"Total events: {total:,}")

    manifest_f = open(work / "manifest.jsonl", "w")
    req_file_idx = 0
    req_f = open(work / f"requests_{req_file_idx:03d}.jsonl", "w")

    batch_n = 0
    lines_in_file = 0
    cur_hashes: list[str] = []
    cur_texts: list[str] = []
    chunk_count = 0
    event_count = 0

    def flush() -> None:
        nonlocal batch_n, lines_in_file, req_file_idx, req_f
        nonlocal cur_hashes, cur_texts
        if not cur_texts:
            return
        custom_id = f"b_{batch_n:06d}"
        manifest_f.write(json.dumps(cur_hashes) + "\n")
        req_f.write(
            json.dumps(
                {
                    "custom_id": custom_id,
                    "method": "POST",
                    "url": "/v1/embeddings",
                    "body": {
                        "model": EMBEDDING_MODEL,
                        "input": cur_texts,
                        "dimensions": EMBEDDING_DIM,
                    },
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        batch_n += 1
        lines_in_file += 1
        cur_hashes = []
        cur_texts = []
        if lines_in_file >= MAX_REQUESTS_PER_FILE:
            req_f.close()
            req_file_idx += 1
            req_f = open(work / f"requests_{req_file_idx:03d}.jsonl", "w")
            lines_in_file = 0

    t0 = time.monotonic()
    cursor = conn.execute(
        "SELECT event_id, content FROM fact_events "
        "WHERE deleted_at IS NULL ORDER BY timestamp ASC",
    )
    for row in cursor:
        content = (row["content"] or "").strip()
        if not content:
            continue
        event_count += 1
        for chunk in chunk_sentences(content):
            text = chunk.text.strip()
            if not text:
                continue
            h = hashlib.sha256(text.encode()).hexdigest()[:32]
            cur_hashes.append(h)
            cur_texts.append(text)
            chunk_count += 1
            if len(cur_texts) >= MAX_TEXTS_PER_REQUEST:
                flush()
        if event_count % 10000 == 0:
            print(f"  {event_count:>7,}/{total:,} events ...", end="\r", flush=True)

    flush()
    manifest_f.close()
    req_f.close()
    conn.close()

    elapsed = time.monotonic() - t0
    print(f"\nPrepared in {_fmt(elapsed)}")
    print(f"  Events with content : {event_count:,}")
    print(f"  Chunks              : {chunk_count:,}")
    print(f"  API request batches : {batch_n:,}")
    print(f"  Request files       : {req_file_idx + 1}")

    est_tokens = chunk_count * 51  # ~51 tok/chunk from earlier sampling
    cost = est_tokens / 1000 * 0.00025
    print(f"  Est. tokens         : {est_tokens:,}")
    print(f"  Est. cost (batch)   : ¥{cost:.2f}")
    print(f"\nWork dir: {work}")
    return 0


# ── submit ──────────────────────────────────────────────────────

def cmd_submit(_args) -> int:
    """Upload JSONL files and create batch jobs on DashScope."""
    work = _work_dir()
    req_files = sorted(work.glob("requests_*.jsonl"))
    if not req_files:
        print("No request files found. Run 'prepare' first.")
        return 1

    client = _get_openai_client()
    state: dict = {"jobs": []}

    for rf in req_files:
        size_mb = rf.stat().st_size / 1024 / 1024
        line_count = sum(1 for _ in open(rf))
        print(f"Uploading {rf.name} ({size_mb:.1f} MB, {line_count:,} requests) ...")
        with open(rf, "rb") as f:
            file_obj = client.files.create(file=f, purpose="batch")
        print(f"  File ID: {file_obj.id}")

        print("  Creating batch job ...")
        batch = client.batches.create(
            input_file_id=file_obj.id,
            endpoint="/v1/embeddings",
            completion_window="24h",
        )
        print(f"  Batch ID: {batch.id} ({batch.status})")

        state["jobs"].append(
            {
                "file": rf.name,
                "input_file_id": file_obj.id,
                "batch_id": batch.id,
                "status": batch.status,
            }
        )

    _save_state(state)
    print(f"\nSubmitted {len(state['jobs'])} job(s). Run 'status --wait' to monitor.")
    return 0


# ── status ──────────────────────────────────────────────────────

def cmd_status(args) -> int:
    """Check and optionally wait for batch job completion."""
    state = _load_state()
    jobs = state.get("jobs", [])
    if not jobs:
        print("No jobs found. Run 'submit' first.")
        return 1

    client = _get_openai_client()

    def refresh() -> bool:
        all_done = True
        for job in jobs:
            terminal = job.get("status") in ("completed", "failed", "expired", "cancelled")
            has_output = job.get("output_file_id") or job.get("error_file_id")
            if terminal and has_output:
                continue
            b = client.batches.retrieve(job["batch_id"])
            job["status"] = b.status
            job["output_file_id"] = getattr(b, "output_file_id", None)
            job["error_file_id"] = getattr(b, "error_file_id", None)
            rc = b.request_counts
            job["counts"] = {
                "total": rc.total if rc else 0,
                "completed": rc.completed if rc else 0,
                "failed": rc.failed if rc else 0,
            }
            if b.status not in ("completed", "failed", "expired", "cancelled"):
                all_done = False
        _save_state(state)
        return all_done

    def show() -> None:
        for job in jobs:
            c = job.get("counts", {})
            print(
                f"  {job['file']}: {job.get('status', '?')} "
                f"({c.get('completed', '?')}/{c.get('total', '?')} done, "
                f"{c.get('failed', 0)} failed)"
            )

    done = refresh()
    show()

    if args.wait and not done:
        print("\nPolling every 60s ...")
        while not done:
            time.sleep(60)
            done = refresh()
            ts = time.strftime("%H:%M:%S")
            print(f"\n[{ts}]")
            show()
        print("\nAll jobs finished!")

    return 0


# ── import ──────────────────────────────────────────────────────

async def cmd_import(args) -> int:
    """Download batch results, build vector cache, and write to L1 DB."""
    import aiosqlite

    from magi.config import get_config
    from magi.core.sqlite import sqlite_connection_async
    from magi.memory.embedding.embedding_service import EmbeddingProfile, EmbeddingResult
    from magi.memory.l1.event_store import (
        EMBEDDING_PROFILES_TABLE,
        EMBEDDING_STATUS_DISABLED,
        EVENT_CHUNKS_TABLE,
        FACT_EVENTS_TABLE,
        L1EventStore,
    )
    from magi.utils.runtime import get_runtime_paths

    work = _work_dir()
    state = _load_state()
    jobs = state.get("jobs", [])

    # -- Verify all jobs completed --
    incomplete = [j for j in jobs if j.get("status") != "completed"]
    if incomplete:
        print(f"ERROR: {len(incomplete)} job(s) not completed:")
        for j in incomplete:
            print(f"  {j['file']}: {j.get('status')}")
        print("Run 'status --wait' first.")
        return 1

    # -- Download result files --
    client = _get_openai_client()
    result_dir = work / "results"
    result_dir.mkdir(exist_ok=True)

    # DashScope does not populate output_file_id on the batch object.
    # Instead, output files are named "<batch_uuid>_<ts>_success.jsonl" and
    # listed via the files API with purpose="batch_output".  Build a lookup
    # so we can resolve output_file_id from the batch_id when needed.
    _output_file_cache: dict[str, str] | None = None

    def _resolve_output_file_id(batch_id: str, explicit_id: str | None) -> str | None:
        if explicit_id:
            return explicit_id
        nonlocal _output_file_cache
        if _output_file_cache is None:
            _output_file_cache = {}
            for f in client.files.list().data:
                if f.purpose == "batch_output" and f.filename and f.filename.endswith("_success.jsonl"):
                    # filename format: "<batch_uuid>_<ts>_success.jsonl"
                    bid = f.filename.split("_")[0]
                    # batch_id format: "batch_<uuid>" → extract uuid part
                    _output_file_cache[bid] = f.id
        # Extract UUID from "batch_<uuid>"
        batch_uuid = batch_id.replace("batch_", "", 1) if batch_id.startswith("batch_") else batch_id
        return _output_file_cache.get(batch_uuid)

    result_files: list[Path] = []
    for job in jobs:
        out_id = _resolve_output_file_id(job["batch_id"], job.get("output_file_id"))
        if not out_id:
            print(f"WARNING: {job['file']} has no output file, skipping")
            continue
        rp = result_dir / f"result_{job['file']}"
        if not rp.exists():
            print(f"Downloading results for {job['file']} ...")
            content = client.files.content(out_id)
            rp.write_bytes(content.read())
            print(f"  Saved {rp.stat().st_size / 1024 / 1024:.1f} MB")
        else:
            print(f"Using cached {rp.name}")
        result_files.append(rp)

    if not result_files:
        print("ERROR: No result files available.")
        return 1

    # -- Load manifest --
    manifest: list[list[str]] = []
    with open(work / "manifest.jsonl") as f:
        for line in f:
            manifest.append(json.loads(line))
    print(f"Manifest: {len(manifest):,} batches")

    # -- Build vector cache DB --
    cache_path = work / "vector_cache.db"
    print(f"\nBuilding vector cache → {cache_path} ...")
    cache_conn = sqlite3.connect(str(cache_path))
    cache_conn.execute("PRAGMA journal_mode=WAL")
    cache_conn.execute("PRAGMA synchronous=NORMAL")
    cache_conn.execute(
        "CREATE TABLE IF NOT EXISTS vector_cache "
        "(text_hash TEXT PRIMARY KEY, vector BLOB)"
    )

    inserted = 0
    api_errors = 0
    for rf in result_files:
        with open(rf) as f:
            for line in f:
                obj = json.loads(line)
                resp = obj.get("response", {})
                if resp.get("status_code") != 200:
                    api_errors += 1
                    continue
                batch_idx = int(obj["custom_id"].split("_")[1])
                hashes = manifest[batch_idx]
                for item in resp["body"]["data"]:
                    idx = item["index"]
                    vec = item["embedding"]
                    blob = struct.pack(f"{len(vec)}f", *vec)
                    cache_conn.execute(
                        "INSERT OR IGNORE INTO vector_cache VALUES (?, ?)",
                        (hashes[idx], blob),
                    )
                    inserted += 1
                if inserted % 100_000 == 0:
                    cache_conn.commit()
                    print(f"  {inserted:,} vectors cached ...", end="\r", flush=True)

    cache_conn.commit()
    cache_conn.close()
    print(f"  Cached {inserted:,} vectors ({api_errors} API errors)")

    # -- CachedEmbeddingService --
    class CachedEmbeddingService:
        """Drop-in MemoryEmbeddingService replacement using pre-computed vectors."""

        def __init__(self, db_path: str):
            self._conn = sqlite3.connect(db_path)

        async def embed_texts(self, texts: list[str]) -> list[EmbeddingResult | None]:
            results: list[EmbeddingResult | None] = []
            for t in texts:
                h = hashlib.sha256(t.strip().encode()).hexdigest()[:32]
                row = self._conn.execute(
                    "SELECT vector FROM vector_cache WHERE text_hash = ?", (h,)
                ).fetchone()
                if row:
                    vec = list(struct.unpack(f"{EMBEDDING_DIM}f", row[0]))
                    results.append(
                        EmbeddingResult(
                            model_name=EMBEDDING_MODEL,
                            dimension=EMBEDDING_DIM,
                            vector=vec,
                        )
                    )
                else:
                    results.append(None)
            return results

        async def embed_text(self, text: str) -> EmbeddingResult | None:
            r = await self.embed_texts([text])
            return r[0]

        def profile_from_result(
            self, result: EmbeddingResult | None, *, text_builder_version: str
        ) -> EmbeddingProfile:
            return EmbeddingProfile.build(
                provider_name="dashscope",
                model_name=EMBEDDING_MODEL,
                dimension=EMBEDDING_DIM,
                text_builder_version=text_builder_version,
            )

        def get_active_profile(
            self, *, text_builder_version: str
        ) -> EmbeddingProfile:
            return self.profile_from_result(
                None, text_builder_version=text_builder_version
            )

        def close(self) -> None:
            self._conn.close()

    # -- Rebuild L1 with cached vectors --
    paths = get_runtime_paths()
    db_path = str(paths.l1_memory_db_path)

    cached_svc = CachedEmbeddingService(str(cache_path))
    store = L1EventStore(
        db_path=db_path,
        embedding_service=cached_svc,
        memory_config_getter=lambda: get_config().agent.memory,
        vector_enabled=True,
        async_embeddings=False,
    )
    await store.initialize()

    try:
        total_events = await store.count_events()

        print(f"\n[1/3] Clearing existing chunks and vectors ...")
        t0 = time.monotonic()
        async with sqlite_connection_async(db_path, profile="hot_write") as db:
            await db.execute(f"DELETE FROM {EVENT_CHUNKS_TABLE}")
            await db.execute(f"DELETE FROM {EMBEDDING_PROFILES_TABLE}")
            await db.execute(
                f"""
                UPDATE {FACT_EVENTS_TABLE}
                SET embedding_status = ?,
                    embedding_profile_id = NULL,
                    embedding_chunk_count = 0,
                    last_embedded_at = NULL
                WHERE deleted_at IS NULL
                """,
                (EMBEDDING_STATUS_DISABLED,),
            )
            await db.commit()
        if store._vector_index is not None:
            await store._vector_index.clear()
        print(f"      Done in {_fmt(time.monotonic() - t0)}")

        print(f"\n[2/3] Importing vectors for {total_events:,} events ...")
        batch_size = args.batch_size
        processed = 0
        offset = 0
        cache_misses = 0
        t_start = time.monotonic()

        while True:
            async with sqlite_connection_async(db_path, profile="hot_write") as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    f"""
                    SELECT * FROM {FACT_EVENTS_TABLE}
                    WHERE deleted_at IS NULL
                    ORDER BY timestamp ASC, id ASC
                    LIMIT ? OFFSET ?
                    """,
                    (batch_size, offset),
                ) as cursor:
                    rows = await cursor.fetchall()
            if not rows:
                break

            events = [store._row_to_memory_event(row) for row in rows]
            await store._maybe_upsert_event_embeddings(events)
            processed += len(events)
            offset += len(rows)

            elapsed = time.monotonic() - t_start
            rate = processed / elapsed if elapsed > 0 else 0
            eta = (total_events - processed) / rate if rate > 0 else 0
            pct = processed * 100 / total_events
            print(
                f"      {processed:>7,}/{total_events:,} ({pct:5.1f}%)  "
                f"{rate:.0f} events/s  "
                f"elapsed {_fmt(elapsed)}  "
                f"ETA {_fmt(eta)}",
                end="\r",
                flush=True,
            )

        elapsed = time.monotonic() - t_start
        print(f"\n      Imported {processed:,} events in {_fmt(elapsed)}")

        # Verify
        print(f"\n[3/3] Verifying ...")
        async with sqlite_connection_async(db_path, profile="hot_write") as db:
            async with db.execute(
                f"SELECT count(*) FROM {EVENT_CHUNKS_TABLE}"
            ) as cur:
                chunk_count = (await cur.fetchone())[0]
            async with db.execute(
                f"SELECT embedding_status, count(*) FROM {FACT_EVENTS_TABLE} "
                f"GROUP BY embedding_status"
            ) as cur:
                status_rows = await cur.fetchall()

        print(f"      Total chunks : {chunk_count:,}")
        for status, count in status_rows:
            print(f"      {status:>10s}   : {count:,}")

    finally:
        await store.shutdown()
        cached_svc.close()

    print("\nDone!")
    return 0


# ── main ────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild L1 embeddings via DashScope Batch File API",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("prepare", help="Chunk events and generate JSONL request files")
    sub.add_parser("submit", help="Upload files and create batch jobs")

    sp_status = sub.add_parser("status", help="Check batch job progress")
    sp_status.add_argument(
        "--wait", action="store_true", help="Poll until all jobs finish"
    )

    sp_import = sub.add_parser(
        "import", help="Download results and write vectors to L1 DB"
    )
    sp_import.add_argument("--batch-size", type=int, default=200)

    args = parser.parse_args()

    if args.command == "prepare":
        return cmd_prepare(args)
    elif args.command == "submit":
        return cmd_submit(args)
    elif args.command == "status":
        return cmd_status(args)
    elif args.command == "import":
        return asyncio.run(cmd_import(args))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
