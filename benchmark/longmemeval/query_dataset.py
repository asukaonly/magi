"""Query previously replayed LongMemEval namespaces and export predictions."""

from __future__ import annotations

import argparse
import asyncio
import json
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


async def query_longmemeval_rows(
    *,
    rows: Sequence[dict[str, Any]],
    eval_service: SupportsQueryService,
    run_id: str,
    output_root: str | Path,
    benchmark_name: str = "longmemeval",
) -> LongMemEvalQueryArtifacts:
    output_dir = build_run_output_dir(
        root_dir=output_root,
        benchmark_name=benchmark_name,
        run_id=run_id,
    )

    traced_predictions: list[dict[str, Any]] = []
    for row in rows:
        question_id = str(row.get("question_id") or "")
        namespace = build_eval_namespace(
            benchmark_name=benchmark_name,
            run_id=run_id,
            question_id=question_id,
        )
        adapted = adapt_longmemeval_entry(row, namespace=namespace)
        query_result = await eval_service.query_memory(adapted.query)
        hypothesis = synthesize_hypothesis_from_hits(hits=query_result.hits)
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


async def _run_cli(args: argparse.Namespace) -> LongMemEvalQueryArtifacts:
    rows = load_longmemeval_rows(args.dataset, limit=args.limit)
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
        )
    finally:
        await runtime.shutdown()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query previously replayed LongMemEval memory.")
    parser.add_argument("--dataset", required=True, help="Path to a LongMemEval JSON dataset file.")
    parser.add_argument("--output-root", default="benchmark/outputs", help="Directory for benchmark outputs.")
    parser.add_argument("--run-id", default="smoke", help="Logical run identifier.")
    parser.add_argument("--limit", type=int, default=None, help="Optional sample limit for quick runs.")
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
