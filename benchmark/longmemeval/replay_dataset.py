"""Replay LongMemEval history into Magi memory without running queries."""

from __future__ import annotations

# ruff: noqa: E402

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = REPO_ROOT / "backend" / "src"
for candidate in (REPO_ROOT, BACKEND_SRC):
    candidate_text = str(candidate)
    if candidate_text not in sys.path:
        sys.path.insert(0, candidate_text)

from benchmark.common.io import write_jsonl
from benchmark.common.paths import build_run_output_dir, resolve_backend_url
from benchmark.longmemeval.adapter import adapt_longmemeval_entry
from benchmark.longmemeval.backend_client import BackendEvalService
from benchmark.longmemeval.runner import load_longmemeval_rows
from magi.memory.eval_support.namespace import build_eval_namespace


class SupportsReplayService(Protocol):
    """Small protocol for replay-only memory ingestion."""

    async def write_records(self, *, namespace: str, records: list[Any]) -> Any:
        """Replay normalized records into memory."""

    async def finalize_replay(
        self,
        *,
        generate_summaries: bool = True,
        flush_l2_projection_jobs: bool = True,
        drain_l2_edge_embeddings: bool = True,
    ) -> dict[str, Any]:
        """Run post-replay summary generation and return L2 pipeline status."""

    async def get_l2_pipeline_stats(self) -> dict[str, Any]:
        """Return current L2 pipeline counters."""

    async def get_background_pending(self) -> dict[str, Any]:
        """Return lightweight backlog stats for background memory workers."""


@dataclass(slots=True)
class LongMemEvalReplayArtifacts:
    """Files produced by a replay-only invocation."""

    output_dir: Path
    manifest_path: Path
    post_replay_path: Path


@dataclass(slots=True)
class ReplayProgress:
    """Progress snapshot for L1 replay writes."""

    question_index: int
    total_questions: int
    question_id: str
    namespace: str
    question_record_count: int
    total_record_count: int


async def replay_longmemeval_rows(
    *,
    rows: Sequence[dict[str, Any]],
    eval_service: SupportsReplayService,
    run_id: str,
    output_root: str | Path,
    benchmark_name: str = "longmemeval",
    progress_reporter: Callable[[ReplayProgress], None] | None = None,
    poll_interval_seconds: float = 5.0,
) -> LongMemEvalReplayArtifacts:
    output_dir = build_run_output_dir(
        root_dir=output_root,
        benchmark_name=benchmark_name,
        run_id=run_id,
    )

    manifest_rows: list[dict[str, Any]] = []
    total_record_count = 0
    total_questions = len(rows)
    for question_index, row in enumerate(rows, start=1):
        question_id = str(row.get("question_id") or "")
        namespace = build_eval_namespace(
            benchmark_name=benchmark_name,
            run_id=run_id,
            question_id=question_id,
        )
        adapted = adapt_longmemeval_entry(row, namespace=namespace)
        await eval_service.write_records(
            namespace=namespace,
            records=adapted.replay_records,
        )
        total_record_count += len(adapted.replay_records)
        if progress_reporter is not None:
            progress_reporter(
                ReplayProgress(
                    question_index=question_index,
                    total_questions=total_questions,
                    question_id=adapted.question_id,
                    namespace=namespace,
                    question_record_count=len(adapted.replay_records),
                    total_record_count=total_record_count,
                )
            )
        manifest_rows.append(
            {
                "question_id": adapted.question_id,
                "question_type": adapted.question_type,
                "namespace": namespace,
                "replay_record_count": len(adapted.replay_records),
                "answer_session_ids": adapted.answer_session_ids,
                "metadata": adapted.metadata,
            }
        )

    manifest_path = write_jsonl(output_dir / "replay_manifest.jsonl", manifest_rows)
    post_replay = {
        "l2_prepare": await eval_service.finalize_replay(
            generate_summaries=False,
            flush_l2_projection_jobs=True,
            drain_l2_edge_embeddings=False,
        )
    }
    post_replay["l2_pipeline_stats"] = await wait_for_l2_pipeline_idle(
        eval_service,
        poll_interval_seconds=poll_interval_seconds,
    )
    post_replay["post_l2_finalize"] = await eval_service.finalize_replay(
        generate_summaries=True,
        flush_l2_projection_jobs=False,
        drain_l2_edge_embeddings=True,
    )
    post_replay["post_l2_pipeline_stats"] = await wait_for_l2_pipeline_idle(
        eval_service,
        poll_interval_seconds=poll_interval_seconds,
    )
    post_replay["background_pending"] = await wait_for_background_idle(
        eval_service,
        poll_interval_seconds=poll_interval_seconds,
    )
    post_replay_path = output_dir / "post_replay.json"
    post_replay_path.write_text(json.dumps(post_replay, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return LongMemEvalReplayArtifacts(
        output_dir=output_dir,
        manifest_path=manifest_path,
        post_replay_path=post_replay_path,
    )


def print_replay_progress(progress: ReplayProgress) -> None:
    """Print per-question L1 replay progress to stdout."""
    print(
        "[L1 replay] "
        f"{progress.question_index}/{progress.total_questions} "
        f"question_id={progress.question_id} "
        f"records={progress.question_record_count} "
        f"total_records={progress.total_record_count}"
    )


def print_l2_pipeline_stats(stats: dict[str, Any]) -> None:
    pending = describe_l2_pending(stats)
    print(
        "[L2 drain] "
        f"extract_pending={pending['extract_pending']} "
        f"extract_active={pending['extract_active']} "
        f"reconcile_pending={pending['reconcile_pending']} "
        f"reconcile_active={pending['reconcile_active']} "
        f"snapshot_pending={pending['snapshot_pending']} "
        f"snapshot_active={pending['snapshot_active']} "
        f"projection_pending={pending['projection_pending']} "
        f"projection_claimed={pending['projection_claimed']}"
    )


def print_background_pending(stats: dict[str, Any]) -> None:
    print(
        "[Background drain] "
        f"l1_embeddings={int(stats.get('l1_embeddings', {}).get('pending', 0))} "
        f"l2_edge_embeddings={int(stats.get('l2_edge_embeddings', {}).get('pending', 0))} "
        f"l3_embeddings={int(stats.get('l3_embeddings', {}).get('pending', 0))} "
        f"l4_embeddings={int(stats.get('l4_embeddings', {}).get('pending', 0))}"
    )


def describe_l2_pending(stats: dict[str, Any]) -> dict[str, int]:
    projection_backlog = dict(stats.get("projection_backlog") or {})
    extract_active = max(int(stats.get("extract_active", 0) or 0), 0)
    reconcile_active = max(int(stats.get("reconcile_active", 0) or 0), 0)
    snapshot_active = max(int(stats.get("snapshot_active", 0) or 0), 0)
    return {
        "extract_pending": max(
            int(stats.get("extract_enqueued", 0))
            - int(stats.get("extract_completed", 0))
            - int(stats.get("extract_failed", 0))
            - int(stats.get("extract_skipped", 0)),
            extract_active,
            0,
        ),
        "extract_active": extract_active,
        "reconcile_pending": max(
            int(stats.get("reconcile_enqueued", 0))
            - int(stats.get("reconcile_completed", 0))
            - int(stats.get("reconcile_failed", 0)),
            reconcile_active,
            0,
        ),
        "reconcile_active": reconcile_active,
        "snapshot_pending": max(
            int(stats.get("snapshot_enqueued", 0))
            - int(stats.get("snapshot_completed", 0))
            - int(stats.get("snapshot_failed", 0)),
            snapshot_active,
            0,
        ),
        "snapshot_active": snapshot_active,
        "projection_pending": max(int(projection_backlog.get("pending", 0) or 0), 0),
        "projection_claimed": max(int(projection_backlog.get("claimed", 0) or 0), 0),
        "projection_failed": max(int(projection_backlog.get("failed", 0) or 0), 0),
    }


def is_l2_pipeline_idle(stats: dict[str, Any]) -> bool:
    pending = describe_l2_pending(stats)
    return all(
        int(pending[key]) == 0
        for key in (
            "extract_pending",
            "extract_active",
            "reconcile_pending",
            "reconcile_active",
            "snapshot_pending",
            "snapshot_active",
            "projection_pending",
            "projection_claimed",
        )
    )


def build_embedding_pending_payload(stats: dict[str, Any]) -> dict[str, Any]:
    return {
        "pending": max(int(stats.get("embedding_queue_size", 0) or 0), 0),
        "worker_running": bool(stats.get("embedding_worker_running", False)),
        "vector_enabled": bool(stats.get("vector_enabled", False)),
        "async_embeddings": bool(stats.get("async_embeddings", False)),
    }


def is_background_idle(stats: dict[str, Any]) -> bool:
    return (
        all(
            int(stats.get("l2", {}).get(key, 0)) == 0
            for key in (
                "extract_pending",
                "extract_active",
                "reconcile_pending",
                "reconcile_active",
                "snapshot_pending",
                "snapshot_active",
            )
        )
        and int(stats.get("l1_embeddings", {}).get("pending", 0)) == 0
        and int(stats.get("l2_edge_embeddings", {}).get("pending", 0)) == 0
        and int(stats.get("l3_embeddings", {}).get("pending", 0)) == 0
        and int(stats.get("l4_embeddings", {}).get("pending", 0)) == 0
    )


async def wait_for_l2_pipeline_idle(
    eval_service: SupportsReplayService,
    *,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    while True:
        stats = await eval_service.get_l2_pipeline_stats()
        print_l2_pipeline_stats(stats)
        if is_l2_pipeline_idle(stats):
            return stats
        await asyncio.sleep(poll_interval_seconds)


async def wait_for_background_idle(
    eval_service: SupportsReplayService,
    *,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    while True:
        stats = await eval_service.get_background_pending()
        print_background_pending(stats)
        if is_background_idle(stats):
            return stats
        await asyncio.sleep(poll_interval_seconds)


async def _run_cli(args: argparse.Namespace) -> LongMemEvalReplayArtifacts:
    rows = load_longmemeval_rows(args.dataset, limit=args.limit)
    backend_url = args.backend_url or resolve_backend_url()
    return await replay_longmemeval_rows(
        rows=rows,
        eval_service=BackendEvalService(backend_url, timeout_seconds=args.request_timeout),
        run_id=args.run_id,
        output_root=args.output_root,
        progress_reporter=print_replay_progress,
        poll_interval_seconds=args.poll_interval_seconds,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay LongMemEval history into Magi memory.")
    parser.add_argument("--dataset", required=True, help="Path to a LongMemEval JSON dataset file.")
    parser.add_argument("--output-root", default="benchmark/outputs", help="Directory for benchmark outputs.")
    parser.add_argument("--run-id", default="smoke", help="Logical run identifier.")
    parser.add_argument("--limit", type=int, default=None, help="Optional sample limit for quick runs.")
    parser.add_argument("--backend-url", default=None, help="Magi backend base URL (auto-detected if omitted).")
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=600.0,
        help="HTTP timeout in seconds for replay and finalize requests.",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=5.0,
        help="Polling interval while waiting for L2 and background queues to drain.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    artifacts = asyncio.run(_run_cli(args))
    print(f"Wrote {artifacts.manifest_path}")
    print(f"Wrote {artifacts.post_replay_path}")
    post_replay = json.loads(artifacts.post_replay_path.read_text(encoding="utf-8"))
    print("L2 pipeline stats:")
    print(json.dumps(post_replay.get("l2_pipeline_stats", {}), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
