"""One-shot LoCoMo pipeline runner for replay and query."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmark.common.paths import build_run_output_dir, resolve_backend_url
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
    backend_url: str | None = None,
    answer_with_llm: bool = True,
    limit: int | None = None,
    finalize: bool = True,
    wait_for_background: bool = True,
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

    replay_callable(
        dataset_path=dataset,
        output_root=output,
        run_id=run_id,
        backend_url=resolved_backend_url,
        limit=limit,
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
    )

    summary_path = run_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "backend_url": resolved_backend_url,
        "dataset": str(dataset),
        "summary": summary,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the full LoCoMo QA benchmark pipeline against Magi backend.")
    parser.add_argument(
        "--dataset",
        default=None,
        help="Path to LoCoMo locomo10.json. Defaults to LOCOMO_ROOT/data/locomo10.json or ~/code/locomo/data/locomo10.json.",
    )
    parser.add_argument("--output-root", default="benchmark/outputs", help="Directory where outputs will be written.")
    parser.add_argument("--run-id", default=None, help="Optional run identifier. Defaults to local timestamp.")
    parser.add_argument("--backend-url", default=None, help="Magi backend base URL (auto-detected if omitted).")
    parser.add_argument("--limit", type=int, default=None, help="Optional sample limit for smoke runs.")
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
        finalize=not args.skip_finalize,
        wait_for_background=not args.skip_background_wait,
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
    query_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
