"""Replay LoCoMo conversations into Magi memory without running queries."""

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
from benchmark.locomo.adapter import adapt_locomo_sample
from benchmark.locomo.runner import apply_qa_limit, load_locomo_samples
from benchmark.longmemeval.backend_client import BackendEvalService
from benchmark.longmemeval.replay_dataset import (
    wait_for_background_idle,
    wait_for_l2_pipeline_idle,
)
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
class LoCoMoReplayArtifacts:
    """Files produced by a replay-only invocation."""

    output_dir: Path
    manifest_path: Path
    post_replay_path: Path


@dataclass(slots=True)
class ReplayProgress:
    """Progress snapshot for LoCoMo conversation replay."""

    sample_index: int
    total_samples: int
    sample_id: str
    namespace: str
    replay_record_count: int
    qa_count: int
    total_record_count: int


async def replay_locomo_samples(
    *,
    samples: Sequence[dict[str, Any]],
    eval_service: SupportsReplayService,
    run_id: str,
    output_root: str | Path,
    benchmark_name: str = "locomo",
    progress_reporter: Callable[[ReplayProgress], None] | None = None,
    poll_interval_seconds: float = 5.0,
    finalize: bool = True,
    wait_for_background: bool = True,
    qa_limit: int | None = None,
) -> LoCoMoReplayArtifacts:
    samples = apply_qa_limit(samples, qa_limit=qa_limit)
    output_dir = build_run_output_dir(
        root_dir=output_root,
        benchmark_name=benchmark_name,
        run_id=run_id,
    )

    manifest_rows: list[dict[str, Any]] = []
    total_record_count = 0
    total_samples = len(samples)
    for sample_index, sample in enumerate(samples, start=1):
        sample_id = str(sample.get("sample_id") or f"sample-{sample_index}")
        namespace = build_eval_namespace(
            benchmark_name=benchmark_name,
            run_id=run_id,
            question_id=sample_id,
        )
        adapted = adapt_locomo_sample(sample, namespace=namespace)
        await eval_service.write_records(
            namespace=namespace,
            records=adapted.replay_records,
        )
        total_record_count += len(adapted.replay_records)
        if progress_reporter is not None:
            progress_reporter(
                ReplayProgress(
                    sample_index=sample_index,
                    total_samples=total_samples,
                    sample_id=adapted.sample_id,
                    namespace=namespace,
                    replay_record_count=len(adapted.replay_records),
                    qa_count=len(adapted.qa_entries),
                    total_record_count=total_record_count,
                )
            )
        manifest_rows.append(
            {
                "sample_id": adapted.sample_id,
                "namespace": namespace,
                "replay_record_count": len(adapted.replay_records),
                "qa_count": len(adapted.qa_entries),
                "speakers": [adapted.speaker_a, adapted.speaker_b],
            }
        )

    manifest_path = write_jsonl(output_dir / "replay_manifest.jsonl", manifest_rows)
    if finalize:
        post_replay = {
            "l2_prepare": await eval_service.finalize_replay(
                generate_summaries=False,
                flush_l2_projection_jobs=True,
                drain_l2_edge_embeddings=False,
            )
        }
    else:
        post_replay = {"finalize": {"status": "skipped"}}

    if wait_for_background:
        post_replay["l2_pipeline_stats"] = await wait_for_l2_pipeline_idle(
            eval_service,
            poll_interval_seconds=poll_interval_seconds,
        )
    else:
        post_replay["l2_pipeline_stats"] = {"status": "skipped"}
        post_replay["background_pending"] = {"status": "skipped"}
    if finalize:
        post_replay["post_l2_finalize"] = await eval_service.finalize_replay(
            generate_summaries=True,
            flush_l2_projection_jobs=False,
            drain_l2_edge_embeddings=True,
        )
    if wait_for_background and finalize:
        post_replay["post_l2_pipeline_stats"] = await wait_for_l2_pipeline_idle(
            eval_service,
            poll_interval_seconds=poll_interval_seconds,
        )
    if wait_for_background:
        post_replay["background_pending"] = await wait_for_background_idle(
            eval_service,
            poll_interval_seconds=poll_interval_seconds,
        )
    post_replay_path = output_dir / "post_replay.json"
    post_replay_path.write_text(
        json.dumps(post_replay, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return LoCoMoReplayArtifacts(
        output_dir=output_dir,
        manifest_path=manifest_path,
        post_replay_path=post_replay_path,
    )


def print_replay_progress(progress: ReplayProgress) -> None:
    """Print per-sample replay progress to stdout."""
    print(
        "[LoCoMo replay] "
        f"{progress.sample_index}/{progress.total_samples} "
        f"sample_id={progress.sample_id} "
        f"records={progress.replay_record_count} "
        f"qas={progress.qa_count} "
        f"total_records={progress.total_record_count}",
        flush=True,
    )


async def _run_cli(args: argparse.Namespace) -> LoCoMoReplayArtifacts:
    samples = load_locomo_samples(args.dataset, limit=args.limit)
    backend_url = args.backend_url or resolve_backend_url()
    return await replay_locomo_samples(
        samples=samples,
        eval_service=BackendEvalService(backend_url, timeout_seconds=args.request_timeout),
        run_id=args.run_id,
        output_root=args.output_root,
        progress_reporter=print_replay_progress,
        poll_interval_seconds=args.poll_interval_seconds,
        finalize=not args.skip_finalize,
        wait_for_background=not args.skip_background_wait,
        qa_limit=args.qa_limit,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay LoCoMo conversations into Magi memory.")
    parser.add_argument(
        "--dataset",
        default=None,
        help="Path to LoCoMo locomo10.json. Defaults to LOCOMO_ROOT/data/locomo10.json or ~/code/locomo/data/locomo10.json.",
    )
    parser.add_argument("--output-root", default="benchmark/outputs", help="Directory for benchmark outputs.")
    parser.add_argument("--run-id", default="smoke", help="Logical run identifier.")
    parser.add_argument("--limit", type=int, default=None, help="Optional sample limit for quick runs.")
    parser.add_argument(
        "--qa-limit",
        type=int,
        default=None,
        help="Optional per-sample QA limit for quick runs.",
    )
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
        help="Polling interval while waiting for memory queues to drain.",
    )
    parser.add_argument(
        "--skip-finalize",
        action="store_true",
        help="Skip post-replay summary generation for fast smoke tests.",
    )
    parser.add_argument(
        "--skip-background-wait",
        action="store_true",
        help="Skip waiting for memory background queues to drain.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    artifacts = asyncio.run(_run_cli(args))
    print(f"Wrote {artifacts.manifest_path}")
    print(f"Wrote {artifacts.post_replay_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
