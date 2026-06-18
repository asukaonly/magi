"""Query previously replayed LoCoMo conversations and export predictions."""

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
from benchmark.common.paths import build_run_output_dir, resolve_backend_url
from benchmark.locomo.adapter import adapt_locomo_sample
from benchmark.locomo.report import (
    build_locomo_predictions_payload,
    build_official_predictions,
    build_prediction_row,
    compute_locomo_summary,
)
from benchmark.locomo.runner import load_locomo_samples, synthesize_locomo_hypothesis
from benchmark.longmemeval.backend_client import BackendEvalService
from magi.memory.eval_support.contracts import EvalMemoryQueryResult
from magi.memory.eval_support.namespace import build_eval_namespace

MAX_QUERY_RETRIES = 3
ERROR_HYPOTHESIS = "__error__"


class SupportsQueryService(Protocol):
    """Small protocol for query-only memory retrieval."""

    async def query_memory(self, query: Any) -> Any:
        """Execute a memory-only retrieval query."""


@dataclass(slots=True)
class LoCoMoQueryArtifacts:
    """Files produced by a query-only invocation."""

    output_dir: Path
    predictions_path: Path
    predictions_with_trace_path: Path
    locomo_predictions_path: Path
    summary_path: Path


@dataclass(slots=True)
class QueryProgress:
    """Progress snapshot for LoCoMo query evaluation."""

    sample_index: int
    total_samples: int
    question_index: int
    total_questions: int
    question_id: str
    namespace: str
    hit_count: int
    total_hit_count: int


async def query_locomo_samples(
    *,
    samples: Sequence[dict[str, Any]],
    eval_service: SupportsQueryService,
    run_id: str,
    output_root: str | Path,
    benchmark_name: str = "locomo",
    progress_reporter: Callable[[QueryProgress], None] | None = None,
    answer_with_llm: bool = False,
    mode: str = "auto",
) -> LoCoMoQueryArtifacts:
    output_dir = build_run_output_dir(
        root_dir=output_root,
        benchmark_name=benchmark_name,
        run_id=run_id,
    )

    traced_predictions: list[dict[str, Any]] = []
    total_questions = sum(len(sample.get("qa") or []) for sample in samples)
    total_hit_count = 0
    absolute_question_index = 0
    total_samples = len(samples)
    for sample_index, sample in enumerate(samples, start=1):
        sample_id = str(sample.get("sample_id") or f"sample-{sample_index}")
        namespace = build_eval_namespace(
            benchmark_name=benchmark_name,
            run_id=run_id,
            question_id=sample_id,
        )
        adapted = adapt_locomo_sample(sample, namespace=namespace)
        for qa_entry in adapted.qa_entries:
            absolute_question_index += 1
            query_obj = replace(qa_entry.query, mode=mode, answer_with_llm=answer_with_llm)
            query_result: EvalMemoryQueryResult | None = None
            last_error: str | None = None
            for attempt in range(1, MAX_QUERY_RETRIES + 1):
                try:
                    query_result = await eval_service.query_memory(query_obj)
                    break
                except Exception as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                    print(
                        f"[LoCoMo query retry] question_id={qa_entry.question_id} "
                        f"attempt={attempt}/{MAX_QUERY_RETRIES} error={last_error}",
                        flush=True,
                    )
                    if attempt < MAX_QUERY_RETRIES:
                        await asyncio.sleep(1.0 * attempt)

            if query_result is None:
                query_result = EvalMemoryQueryResult(
                    hits=[],
                    trace={"error": last_error, "skipped": True},
                )

            hit_count = len(query_result.hits)
            total_hit_count += hit_count
            if progress_reporter is not None:
                progress_reporter(
                    QueryProgress(
                        sample_index=sample_index,
                        total_samples=total_samples,
                        question_index=absolute_question_index,
                        total_questions=total_questions,
                        question_id=qa_entry.question_id,
                        namespace=namespace,
                        hit_count=hit_count,
                        total_hit_count=total_hit_count,
                    )
                )

            skipped = query_result.trace.get("skipped", False)
            if skipped:
                hypothesis = ERROR_HYPOTHESIS
            else:
                hypothesis = synthesize_locomo_hypothesis(
                    answer=query_result.answer,
                    hits=query_result.hits,
                    category=qa_entry.category,
                    fallback="No information available" if qa_entry.category == 5 else "unknown",
                )
            traced_predictions.append(
                build_prediction_row(
                    sample_id=qa_entry.sample_id,
                    qa_index=qa_entry.qa_index,
                    question_id=qa_entry.question_id,
                    category=qa_entry.category,
                    category_label=qa_entry.category_label,
                    question=qa_entry.question,
                    expected_answer=qa_entry.expected_answer,
                    evidence=qa_entry.evidence,
                    answer_session_ids=qa_entry.answer_session_ids,
                    hypothesis=hypothesis,
                    namespace=namespace,
                    retrieved_session_ids=query_result.retrieved_session_ids,
                    retrieved_turn_ids=query_result.retrieved_turn_ids,
                    retrieved_event_ids=query_result.retrieved_event_ids,
                    trace=query_result.trace,
                    answer_trace=query_result.answer_trace,
                    metadata=qa_entry.metadata,
                )
            )

    predictions_with_trace_path = write_jsonl(
        output_dir / "predictions_with_trace.jsonl",
        traced_predictions,
    )
    predictions_path = write_jsonl(
        output_dir / "predictions.jsonl",
        build_official_predictions(traced_predictions),
    )
    locomo_predictions = build_locomo_predictions_payload(
        samples=samples,
        prediction_rows=traced_predictions,
    )
    locomo_predictions_path = output_dir / "locomo_predictions.json"
    locomo_predictions_path.write_text(
        json.dumps(locomo_predictions, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summary = compute_locomo_summary(traced_predictions)
    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return LoCoMoQueryArtifacts(
        output_dir=output_dir,
        predictions_path=predictions_path,
        predictions_with_trace_path=predictions_with_trace_path,
        locomo_predictions_path=locomo_predictions_path,
        summary_path=summary_path,
    )


def print_query_progress(progress: QueryProgress) -> None:
    """Print per-question query progress to stdout."""
    print(
        "[LoCoMo query] "
        f"{progress.question_index}/{progress.total_questions} "
        f"sample={progress.sample_index}/{progress.total_samples} "
        f"question_id={progress.question_id} "
        f"hits={progress.hit_count} "
        f"total_hits={progress.total_hit_count}",
        flush=True,
    )


async def _run_cli(args: argparse.Namespace) -> LoCoMoQueryArtifacts:
    samples = load_locomo_samples(args.dataset, limit=args.limit)
    backend_url = args.backend_url or resolve_backend_url()
    return await query_locomo_samples(
        samples=samples,
        eval_service=BackendEvalService(backend_url, timeout_seconds=args.request_timeout),
        run_id=args.run_id,
        output_root=args.output_root,
        progress_reporter=print_query_progress,
        answer_with_llm=args.answer_with_llm,
        mode=args.mode,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query previously replayed LoCoMo memory.")
    parser.add_argument(
        "--dataset",
        default=None,
        help="Path to LoCoMo locomo10.json. Defaults to LOCOMO_ROOT/data/locomo10.json or ~/code/locomo/data/locomo10.json.",
    )
    parser.add_argument("--output-root", default="benchmark/outputs", help="Directory for benchmark outputs.")
    parser.add_argument("--run-id", default="smoke", help="Existing run identifier used during replay.")
    parser.add_argument("--limit", type=int, default=None, help="Optional sample limit for quick runs.")
    parser.add_argument("--backend-url", default=None, help="Magi backend base URL (auto-detected if omitted).")
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=120.0,
        help="HTTP timeout in seconds for query requests.",
    )
    parser.add_argument(
        "--answer-with-llm",
        action="store_true",
        help="Use the backend LLM to synthesize a final answer from retrieved hits.",
    )
    parser.add_argument(
        "--mode",
        default="auto",
        help="Memory retrieval mode hint (auto|detail|summary|experience|graph|strategy|l1_only).",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    artifacts = asyncio.run(_run_cli(args))
    print(f"Wrote {artifacts.predictions_path}")
    print(f"Wrote {artifacts.predictions_with_trace_path}")
    print(f"Wrote {artifacts.locomo_predictions_path}")
    print(f"Wrote {artifacts.summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
