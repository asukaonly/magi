"""Query previously replayed LongMemEval namespaces and export predictions."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

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
from benchmark.longmemeval.report import compute_session_recall_summary, export_official_predictions
from benchmark.longmemeval.runner import create_default_runtime, load_longmemeval_rows, synthesize_hypothesis_from_hits
from magi.memory.eval_support.namespace import build_eval_namespace


class SupportsQueryService(Protocol):
    """Small protocol for query-only memory retrieval."""

    async def query_memory(self, query: Any) -> Any:
        """Execute a memory-only retrieval query."""


@dataclass(slots=True)
class LongMemEvalQueryArtifacts:
    """Files produced by a query-only invocation."""

    output_dir: Path
    predictions_path: Path
    predictions_with_trace_path: Path
    summary_path: Path


@dataclass(slots=True)
class QueryProgress:
    """Progress snapshot for memory query evaluation."""

    question_index: int
    total_questions: int
    question_id: str
    namespace: str
    hit_count: int
    total_hit_count: int


async def query_longmemeval_rows(
    *,
    rows: Sequence[dict[str, Any]],
    eval_service: SupportsQueryService,
    run_id: str,
    output_root: str | Path,
    benchmark_name: str = "longmemeval",
    progress_reporter: Callable[[QueryProgress], None] | None = None,
    answer_with_llm: bool = False,
    mode: str = "auto",
) -> LongMemEvalQueryArtifacts:
    output_dir = build_run_output_dir(
        root_dir=output_root,
        benchmark_name=benchmark_name,
        run_id=run_id,
    )

    traced_predictions: list[dict[str, Any]] = []
    total_hit_count = 0
    total_questions = len(rows)
    for question_index, row in enumerate(rows, start=1):
        question_id = str(row.get("question_id") or "")
        namespace = build_eval_namespace(
            benchmark_name=benchmark_name,
            run_id=run_id,
            question_id=question_id,
        )
        adapted = adapt_longmemeval_entry(row, namespace=namespace)
        query_result = await eval_service.query_memory(
            replace(adapted.query, mode=mode, answer_with_llm=answer_with_llm)
        )
        hit_count = len(query_result.hits)
        total_hit_count += hit_count
        if progress_reporter is not None:
            progress_reporter(
                QueryProgress(
                    question_index=question_index,
                    total_questions=total_questions,
                    question_id=adapted.question_id,
                    namespace=namespace,
                    hit_count=hit_count,
                    total_hit_count=total_hit_count,
                )
            )
        hypothesis = query_result.answer or synthesize_hypothesis_from_hits(hits=query_result.hits)
        traced_predictions.append(
            {
                "question_id": adapted.question_id,
                "question_type": adapted.question_type,
                "expected_answer": adapted.expected_answer,
                "answer_session_ids": adapted.answer_session_ids,
                "namespace": namespace,
                "hypothesis": hypothesis,
                "retrieved_session_ids": query_result.retrieved_session_ids,
                "retrieved_turn_ids": query_result.retrieved_turn_ids,
                "retrieved_event_ids": query_result.retrieved_event_ids,
                "trace": query_result.trace,
                "answer_trace": query_result.answer_trace,
                "metadata": adapted.metadata,
            }
        )

    predictions_with_trace_path = write_jsonl(
        output_dir / "predictions_with_trace.jsonl",
        traced_predictions,
    )
    predictions_path = export_official_predictions(output_dir / "predictions.jsonl", traced_predictions)
    summary = compute_session_recall_summary(traced_predictions, k=1)
    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return LongMemEvalQueryArtifacts(
        output_dir=output_dir,
        predictions_path=predictions_path,
        predictions_with_trace_path=predictions_with_trace_path,
        summary_path=summary_path,
    )


def print_query_progress(progress: QueryProgress) -> None:
    """Print per-question memory query progress to stdout."""
    print(
        "[Query replay] "
        f"{progress.question_index}/{progress.total_questions} "
        f"question_id={progress.question_id} "
        f"hits={progress.hit_count} "
        f"total_hits={progress.total_hit_count}"
    )


async def _run_cli(args: argparse.Namespace) -> LongMemEvalQueryArtifacts:
    rows = load_longmemeval_rows(args.dataset, limit=args.limit)
    if args.backend_url:
        return await query_longmemeval_rows(
            rows=rows,
            eval_service=BackendEvalService(args.backend_url),
            run_id=args.run_id,
            output_root=args.output_root,
            progress_reporter=print_query_progress,
            answer_with_llm=args.answer_with_llm,
            mode=args.mode,
        )

    output_dir = build_run_output_dir(
        root_dir=args.output_root,
        benchmark_name="longmemeval",
        run_id=args.run_id,
    )
    runtime = await create_default_runtime(state_dir=output_dir / "state")
    try:
        return await query_longmemeval_rows(
            rows=rows,
            eval_service=runtime.service,
            run_id=args.run_id,
            output_root=args.output_root,
            progress_reporter=print_query_progress,
            answer_with_llm=args.answer_with_llm,
            mode=args.mode,
        )
    finally:
        await runtime.shutdown()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query previously replayed LongMemEval memory.")
    parser.add_argument("--dataset", required=True, help="Path to a LongMemEval JSON dataset file.")
    parser.add_argument("--output-root", default="benchmark/outputs", help="Directory for benchmark outputs.")
    parser.add_argument("--run-id", default="smoke", help="Logical run identifier.")
    parser.add_argument("--limit", type=int, default=None, help="Optional sample limit for quick runs.")
    parser.add_argument("--backend-url", default=None, help="Optional Magi backend base URL for full-memory eval.")
    parser.add_argument(
        "--answer-with-llm",
        action="store_true",
        help="Use the backend LLM to synthesize a final answer from retrieved hits.",
    )
    parser.add_argument(
        "--mode",
        default="auto",
        help="Memory retrieval mode hint (auto|detail|summary|experience|graph|strategy).",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    artifacts = asyncio.run(_run_cli(args))
    print(f"Wrote {artifacts.predictions_path}")
    print(f"Wrote {artifacts.predictions_with_trace_path}")
    print(f"Wrote {artifacts.summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
