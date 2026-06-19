"""One-shot LoCoMo pipeline runner for replay and query."""

from __future__ import annotations

# ruff: noqa: E402

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmark.common.paths import build_run_output_dir, resolve_backend_url
from benchmark.locomo.error_report import run_error_analysis
from benchmark.locomo.llm_judge import DEFAULT_JUDGE_MODEL, main as llm_judge_main
from benchmark.locomo.query_dataset import main as query_main
from benchmark.locomo.replay_dataset import main as replay_main
from benchmark.locomo.runner import format_run_id, resolve_locomo_dataset


def run_locomo_pipeline(
    *,
    dataset_path: str | Path | None,
    output_root: str | Path,
    run_id: str,
    replay_runner: Callable[..., Any] | None = None,
    query_runner: Callable[..., Any] | None = None,
    judge_runner: Callable[..., Any] | None = None,
    backend_url: str | None = None,
    answer_with_llm: bool = True,
    limit: int | None = None,
    qa_limit: int | None = None,
    finalize: bool = True,
    wait_for_background: bool = True,
    llm_judge: bool = True,
    judge_model: str = DEFAULT_JUDGE_MODEL,
    judge_concurrency: int = 4,
) -> dict[str, Any]:
    dataset = resolve_locomo_dataset(dataset_path)
    output = Path(output_root)
    run_dir = build_run_output_dir(
        root_dir=output,
        benchmark_name="locomo",
        run_id=run_id,
    )
    resolved_backend_url = backend_url or resolve_backend_url()
    replay_callable = replay_runner or _invoke_replay
    query_callable = query_runner or _invoke_query
    judge_callable = judge_runner or _invoke_llm_judge

    replay_callable(
        dataset_path=dataset,
        output_root=output,
        run_id=run_id,
        backend_url=resolved_backend_url,
        limit=limit,
        qa_limit=qa_limit,
        finalize=finalize,
        wait_for_background=wait_for_background,
    )
    query_callable(
        dataset_path=dataset,
        output_root=output,
        run_id=run_id,
        backend_url=resolved_backend_url,
        answer_with_llm=answer_with_llm,
        limit=limit,
        qa_limit=qa_limit,
    )

    llm_judge_summary: dict[str, Any]
    if llm_judge:
        judge_callable(
            output_root=output,
            run_id=run_id,
            judge_model=judge_model,
            judge_concurrency=judge_concurrency,
            qa_limit=qa_limit,
        )
        llm_judge_path = run_dir / "llm_judge_summary.json"
        llm_judge_summary = (
            json.loads(llm_judge_path.read_text(encoding="utf-8"))
            if llm_judge_path.exists()
            else {"status": "missing"}
        )
    else:
        llm_judge_summary = {"status": "skipped", "reason": "disabled by --skip-llm-judge"}

    error_report_artifacts = run_error_analysis(
        predictions_with_trace_path=run_dir / "predictions_with_trace.jsonl",
        output_dir=run_dir,
    )
    error_report_summary = json.loads(
        error_report_artifacts.summary_path.read_text(encoding="utf-8")
    )
    print(f"Wrote {error_report_artifacts.csv_path}")
    print(f"Wrote {error_report_artifacts.jsonl_path}")
    print(f"Wrote {error_report_artifacts.summary_path}")

    summary_path = run_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "backend_url": resolved_backend_url,
        "dataset": str(dataset),
        "summary": summary,
        "llm_judge": llm_judge_summary,
        "error_report": error_report_summary,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the full LoCoMo QA benchmark pipeline against Magi backend."
    )
    parser.add_argument(
        "--dataset",
        default=None,
        help="Path to LoCoMo locomo10.json. Defaults to LOCOMO_ROOT/data/locomo10.json or ~/code/locomo/data/locomo10.json.",
    )
    parser.add_argument(
        "--output-root",
        default="benchmark/outputs",
        help="Directory where outputs will be written.",
    )
    parser.add_argument(
        "--run-id", default=None, help="Optional run identifier. Defaults to local timestamp."
    )
    parser.add_argument(
        "--backend-url", default=None, help="Magi backend base URL (auto-detected if omitted)."
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Optional sample limit for smoke runs."
    )
    parser.add_argument(
        "--qa-limit",
        type=int,
        default=None,
        help="Optional per-sample QA limit for smoke runs.",
    )
    parser.add_argument(
        "--no-answer-with-llm",
        action="store_true",
        help="Skip backend LLM answer synthesis and use retrieved snippets as predictions.",
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
    parser.add_argument(
        "--skip-llm-judge",
        action="store_true",
        help="Skip LoCoMo LLM-as-judge scoring.",
    )
    parser.add_argument(
        "--judge-model",
        default=DEFAULT_JUDGE_MODEL,
        help="OpenAI-compatible model used for LoCoMo LLM-as-judge scoring.",
    )
    parser.add_argument(
        "--judge-concurrency",
        type=int,
        default=4,
        help="Maximum concurrent LoCoMo judge requests.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run_locomo_pipeline(
        dataset_path=args.dataset,
        output_root=args.output_root,
        run_id=args.run_id or format_run_id(),
        backend_url=args.backend_url,
        answer_with_llm=not args.no_answer_with_llm,
        limit=args.limit,
        qa_limit=args.qa_limit,
        finalize=not args.skip_finalize,
        wait_for_background=not args.skip_background_wait,
        llm_judge=not args.skip_llm_judge,
        judge_model=args.judge_model,
        judge_concurrency=args.judge_concurrency,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _invoke_replay(
    *,
    dataset_path: Path,
    output_root: Path,
    run_id: str,
    backend_url: str,
    limit: int | None,
    qa_limit: int | None,
    finalize: bool,
    wait_for_background: bool,
) -> None:
    argv = [
        "--dataset",
        str(dataset_path),
        "--output-root",
        str(output_root),
        "--run-id",
        run_id,
        "--backend-url",
        backend_url,
    ]
    if limit is not None:
        argv.extend(["--limit", str(limit)])
    if qa_limit is not None:
        argv.extend(["--qa-limit", str(qa_limit)])
    if not finalize:
        argv.append("--skip-finalize")
    if not wait_for_background:
        argv.append("--skip-background-wait")
    replay_main(argv)


def _invoke_query(
    *,
    dataset_path: Path,
    output_root: Path,
    run_id: str,
    backend_url: str,
    answer_with_llm: bool,
    limit: int | None,
    qa_limit: int | None,
) -> None:
    argv = [
        "--dataset",
        str(dataset_path),
        "--output-root",
        str(output_root),
        "--run-id",
        run_id,
        "--backend-url",
        backend_url,
    ]
    if answer_with_llm:
        argv.append("--answer-with-llm")
    if limit is not None:
        argv.extend(["--limit", str(limit)])
    if qa_limit is not None:
        argv.extend(["--qa-limit", str(qa_limit)])
    query_main(argv)


def _invoke_llm_judge(
    *,
    output_root: Path,
    run_id: str,
    judge_model: str,
    judge_concurrency: int,
    qa_limit: int | None,
) -> None:
    argv = [
        "--output-root",
        str(output_root),
        "--run-id",
        run_id,
        "--judge-model",
        judge_model,
        "--judge-concurrency",
        str(judge_concurrency),
    ]
    llm_judge_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
