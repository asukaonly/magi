"""Replay LongMemEval history into Magi memory without running queries."""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = REPO_ROOT / "backend" / "src"
for candidate in (REPO_ROOT, BACKEND_SRC):
    candidate_text = str(candidate)
    if candidate_text not in sys.path:
        sys.path.insert(0, candidate_text)

from benchmark.common.io import write_jsonl
from benchmark.common.paths import build_run_output_dir
from benchmark.longmemeval.adapter import adapt_longmemeval_entry
from benchmark.longmemeval.backend_client import BackendEvalService
from benchmark.longmemeval.runner import create_default_runtime, load_longmemeval_rows
from magi.memory.eval_support.namespace import build_eval_namespace


class SupportsReplayService(Protocol):
    """Small protocol for replay-only memory ingestion."""

    async def write_records(self, *, namespace: str, records: list[Any]) -> Any:
        """Replay normalized records into memory."""


@dataclass(slots=True)
class LongMemEvalReplayArtifacts:
    """Files produced by a replay-only invocation."""

    output_dir: Path
    manifest_path: Path


async def replay_longmemeval_rows(
    *,
    rows: Sequence[dict[str, Any]],
    eval_service: SupportsReplayService,
    run_id: str,
    output_root: str | Path,
    benchmark_name: str = "longmemeval",
) -> LongMemEvalReplayArtifacts:
    output_dir = build_run_output_dir(
        root_dir=output_root,
        benchmark_name=benchmark_name,
        run_id=run_id,
    )

    manifest_rows: list[dict[str, Any]] = []
    for row in rows:
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
    return LongMemEvalReplayArtifacts(output_dir=output_dir, manifest_path=manifest_path)


async def _run_cli(args: argparse.Namespace) -> LongMemEvalReplayArtifacts:
    rows = load_longmemeval_rows(args.dataset, limit=args.limit)
    if args.backend_url:
        return await replay_longmemeval_rows(
            rows=rows,
            eval_service=BackendEvalService(args.backend_url),
            run_id=args.run_id,
            output_root=args.output_root,
        )

    output_dir = build_run_output_dir(
        root_dir=args.output_root,
        benchmark_name="longmemeval",
        run_id=args.run_id,
    )
    runtime = await create_default_runtime(state_dir=output_dir / "state")
    try:
        return await replay_longmemeval_rows(
            rows=rows,
            eval_service=runtime.service,
            run_id=args.run_id,
            output_root=args.output_root,
        )
    finally:
        await runtime.shutdown()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay LongMemEval history into Magi memory.")
    parser.add_argument("--dataset", required=True, help="Path to a LongMemEval JSON dataset file.")
    parser.add_argument("--output-root", default="benchmark/outputs", help="Directory for benchmark outputs.")
    parser.add_argument("--run-id", default="smoke", help="Logical run identifier.")
    parser.add_argument("--limit", type=int, default=None, help="Optional sample limit for quick runs.")
    parser.add_argument("--backend-url", default=None, help="Optional Magi backend base URL for full-memory eval.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    artifacts = asyncio.run(_run_cli(args))
    print(f"Wrote {artifacts.manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
