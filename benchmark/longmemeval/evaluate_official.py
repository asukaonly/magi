"""Wrapper around LongMemEval's official QA evaluator."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@dataclass(slots=True)
class OfficialEvalArtifacts:
    """Files produced by the official evaluator wrapper."""

    predictions_path: Path
    eval_results_path: Path
    summary_path: Path


def build_predictions_path(*, output_root: str | Path, run_id: str) -> Path:
    return Path(output_root) / "longmemeval" / run_id / "predictions.jsonl"


def build_official_eval_command(
    *,
    longmemeval_root: str | Path,
    dataset_path: str | Path,
    output_root: str | Path,
    run_id: str,
    judge_model: str,
    python_bin: str,
) -> list[str]:
    predictions_path = build_predictions_path(output_root=output_root, run_id=run_id)
    return [
        python_bin,
        str(Path(longmemeval_root) / "src" / "evaluation" / "evaluate_qa.py"),
        judge_model,
        str(predictions_path),
        str(Path(dataset_path)),
    ]


def summarize_official_eval_results(*, eval_results_path: str | Path, ref_path: str | Path) -> dict[str, Any]:
    eval_rows = [json.loads(line) for line in Path(eval_results_path).read_text(encoding="utf-8").splitlines() if line.strip()]
    ref_rows = json.loads(Path(ref_path).read_text(encoding="utf-8"))
    ref_by_qid = {str(row["question_id"]): row for row in ref_rows}

    type_to_scores: dict[str, list[int]] = {}
    all_scores: list[int] = []
    abstention_scores: list[int] = []

    for row in eval_rows:
        qid = str(row["question_id"])
        ref = ref_by_qid[qid]
        qtype = str(ref["question_type"])
        score = 1 if bool(row.get("autoeval_label", {}).get("label", False)) else 0
        type_to_scores.setdefault(qtype, []).append(score)
        all_scores.append(score)
        if "_abs" in qid:
            abstention_scores.append(score)

    task_metrics = {
        qtype: {
            "accuracy": _round4(sum(scores) / len(scores)),
            "count": len(scores),
        }
        for qtype, scores in type_to_scores.items()
    }
    task_averaged_accuracy = _round4(
        sum(metric["accuracy"] for metric in task_metrics.values()) / len(task_metrics)
    ) if task_metrics else 0.0
    return {
        "overall_accuracy": _round4(sum(all_scores) / len(all_scores)) if all_scores else 0.0,
        "task_averaged_accuracy": task_averaged_accuracy,
        "abstention_accuracy": _round4(sum(abstention_scores) / len(abstention_scores)) if abstention_scores else 0.0,
        "task_metrics": task_metrics,
    }


def run_official_evaluation(
    *,
    longmemeval_root: str | Path,
    dataset_path: str | Path,
    output_root: str | Path,
    run_id: str,
    judge_model: str = "gpt-4o",
    python_bin: str = sys.executable,
    runner: Callable[[list[str]], None] | None = None,
) -> OfficialEvalArtifacts:
    predictions_path = build_predictions_path(output_root=output_root, run_id=run_id)
    if not predictions_path.exists():
        raise FileNotFoundError(f"Predictions file not found: {predictions_path}")

    command = build_official_eval_command(
        longmemeval_root=longmemeval_root,
        dataset_path=dataset_path,
        output_root=output_root,
        run_id=run_id,
        judge_model=judge_model,
        python_bin=python_bin,
    )
    run_callable = runner or _default_runner
    run_callable(command)

    eval_results_path = predictions_path.with_name(
        f"{predictions_path.name}.eval-results-{judge_model}"
    )
    if not eval_results_path.exists():
        raise FileNotFoundError(f"Official eval did not produce result file: {eval_results_path}")

    summary = summarize_official_eval_results(
        eval_results_path=eval_results_path,
        ref_path=dataset_path,
    )
    summary_path = predictions_path.parent / "official_eval_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return OfficialEvalArtifacts(
        predictions_path=predictions_path,
        eval_results_path=eval_results_path,
        summary_path=summary_path,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run LongMemEval's official QA evaluator for a Magi benchmark run.")
    parser.add_argument("--longmemeval-root", required=True, help="Path to a local LongMemEval checkout.")
    parser.add_argument("--dataset", required=True, help="Path to the LongMemEval reference dataset JSON.")
    parser.add_argument("--output-root", default="benchmark/outputs", help="Directory containing benchmark outputs.")
    parser.add_argument("--run-id", required=True, help="Benchmark run identifier.")
    parser.add_argument("--judge-model", default="gpt-4o", help="Judge model short name supported by LongMemEval.")
    parser.add_argument("--python-bin", default=sys.executable, help="Python executable used to run official scripts.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    artifacts = run_official_evaluation(
        longmemeval_root=args.longmemeval_root,
        dataset_path=args.dataset,
        output_root=args.output_root,
        run_id=args.run_id,
        judge_model=args.judge_model,
        python_bin=args.python_bin,
    )
    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    print(f"Wrote {artifacts.eval_results_path}")
    print(f"Wrote {artifacts.summary_path}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _default_runner(command: list[str]) -> None:
    subprocess.run(command, check=True)


def _round4(value: float) -> float:
    return round(float(value), 4)


if __name__ == "__main__":
    raise SystemExit(main())
