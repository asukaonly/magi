"""One-shot LongMemEval pipeline runner for replay, query, and official scoring."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmark.common.paths import build_run_output_dir, resolve_backend_url
from benchmark.longmemeval.evaluate_official import run_official_evaluation
from benchmark.longmemeval.query_dataset import main as query_main
from benchmark.longmemeval.replay_dataset import main as replay_main

DEFAULT_BACKEND_URL: str | None = None  # resolved lazily from ~/.magi/config/agent.yaml
DEFAULT_LONGMEMEVAL_ROOT = REPO_ROOT.parent / "LongMemEval"


def format_run_id(now: datetime | None = None) -> str:
    moment = now or datetime.now()
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def resolve_longmemeval_root() -> Path:
    env_value = os.getenv("LONGMEMEVAL_ROOT")
    if env_value:
        path = Path(env_value).expanduser()
        if path.exists():
            return path
    if DEFAULT_LONGMEMEVAL_ROOT.exists():
        return DEFAULT_LONGMEMEVAL_ROOT
    raise FileNotFoundError(
        "LongMemEval root not found. Set LONGMEMEVAL_ROOT or create "
        f"{DEFAULT_LONGMEMEVAL_ROOT}."
    )


def run_longmemeval_pipeline(
    *,
    dataset_path: str | Path,
    output_root: str | Path,
    run_id: str,
    replay_runner: Callable[..., Any] | None = None,
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

    resolved_backend_url = DEFAULT_BACKEND_URL or resolve_backend_url()

    replay_callable = replay_runner or _invoke_replay
    query_callable = query_runner or _invoke_query
    official_callable = official_eval_runner or run_official_evaluation

    replay_callable(
        dataset_path=dataset,
        output_root=output,
        run_id=run_id,
        backend_url=resolved_backend_url,
    )
    query_callable(
        dataset_path=dataset,
        output_root=output,
        run_id=run_id,
        backend_url=resolved_backend_url,
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
        "backend_url": resolved_backend_url,
        "dataset": str(dataset),
        "official_eval": official_summary,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the full LongMemEval benchmark pipeline against Magi backend.")
    parser.add_argument("--dataset", required=True, help="Path to the LongMemEval dataset JSON file.")
    parser.add_argument("--output-root", required=True, help="Directory where benchmark outputs will be written.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    run_id = format_run_id()
    summary = run_longmemeval_pipeline(
        dataset_path=args.dataset,
        output_root=args.output_root,
        run_id=run_id,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _invoke_replay(*, dataset_path: Path, output_root: Path, run_id: str, backend_url: str) -> None:
    replay_main(
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
