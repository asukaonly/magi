"""Rerun LongMemEval query and scoring against previously replayed memory."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmark.common.paths import build_run_output_dir
from benchmark.longmemeval.evaluate_official import run_official_evaluation
from benchmark.longmemeval.query_dataset import main as query_main
from benchmark.longmemeval.run_all import DEFAULT_BACKEND_URL, resolve_longmemeval_root


def run_query_and_score_pipeline(
    *,
    dataset_path: str | Path,
    output_root: str | Path,
    run_id: str,
    query_runner: Callable[..., Any] | None = None,
    official_eval_runner: Callable[..., Any] | None = None,
    longmemeval_root: str | Path | None = None,
) -> dict[str, Any]:
    dataset = Path(dataset_path)
    output = Path(output_root)
    resolved_longmemeval_root = Path(longmemeval_root) if longmemeval_root is not None else resolve_longmemeval_root()
    run_dir = build_run_output_dir(
        root_dir=output,
        benchmark_name="longmemeval",
        run_id=run_id,
    )

    query_callable = query_runner or _invoke_query
    official_callable = official_eval_runner or run_official_evaluation

    query_callable(
        dataset_path=dataset,
        output_root=output,
        run_id=run_id,
        backend_url=DEFAULT_BACKEND_URL,
    )

    official_artifacts = None
    if os.getenv("OPENAI_API_KEY"):
        official_artifacts = official_callable(
            longmemeval_root=resolved_longmemeval_root,
            dataset_path=dataset,
            output_root=output,
            run_id=run_id,
        )
    else:
        print("Skipping official evaluation because OPENAI_API_KEY is not set.")

    summary_path = getattr(official_artifacts, "summary_path", None)
    official_summary = {}
    if summary_path is not None and Path(summary_path).exists():
        official_summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    elif official_artifacts is None:
        official_summary = {
            "status": "skipped",
            "reason": "OPENAI_API_KEY is not set",
        }

    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "backend_url": DEFAULT_BACKEND_URL,
        "dataset": str(dataset),
        "official_eval": official_summary,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rerun LongMemEval query and scoring against previously replayed Magi memory."
    )
    parser.add_argument("--dataset", required=True, help="Path to the LongMemEval dataset JSON file.")
    parser.add_argument("--output-root", required=True, help="Directory where benchmark outputs are stored.")
    parser.add_argument("--run-id", required=True, help="Existing run identifier used during replay.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run_query_and_score_pipeline(
        dataset_path=args.dataset,
        output_root=args.output_root,
        run_id=args.run_id,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _invoke_query(*, dataset_path: Path, output_root: Path, run_id: str, backend_url: str) -> None:
    query_main(
        [
            "--dataset",
            str(dataset_path),
            "--output-root",
            str(output_root),
            "--run-id",
            run_id,
            "--backend-url",
            backend_url,
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
