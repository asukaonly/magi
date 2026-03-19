"""Tests for the LongMemEval official evaluation wrapper."""

from __future__ import annotations

import json
from pathlib import Path

from benchmark.longmemeval.evaluate_official import (
    build_official_eval_command,
    run_official_evaluation,
    summarize_official_eval_results,
)


def test_build_official_eval_command_targets_current_run_predictions(tmp_path) -> None:
    output_root = tmp_path / "outputs"
    command = build_official_eval_command(
        longmemeval_root=tmp_path / "LongMemEval",
        dataset_path=tmp_path / "oracle.json",
        output_root=output_root,
        run_id="oracle-backend",
        judge_model="gpt-4o",
        python_bin="python3",
    )

    assert command == [
        "python3",
        str(tmp_path / "LongMemEval" / "src" / "evaluation" / "evaluate_qa.py"),
        "gpt-4o",
        str(output_root / "longmemeval" / "oracle-backend" / "predictions.jsonl"),
        str(tmp_path / "oracle.json"),
    ]


def test_summarize_official_eval_results_matches_expected_metrics(tmp_path) -> None:
    ref_path = tmp_path / "oracle.json"
    eval_results_path = tmp_path / "predictions.jsonl.eval-results-gpt-4o"

    ref_path.write_text(
        json.dumps(
            [
                {"question_id": "q-1", "question_type": "multi-session"},
                {"question_id": "q-2", "question_type": "knowledge-update"},
                {"question_id": "q-3_abs", "question_type": "temporal-reasoning"},
            ]
        ),
        encoding="utf-8",
    )
    eval_results_path.write_text(
        "\n".join(
            [
                json.dumps({"question_id": "q-1", "autoeval_label": {"model": "gpt-4o-2024-08-06", "label": True}}),
                json.dumps({"question_id": "q-2", "autoeval_label": {"model": "gpt-4o-2024-08-06", "label": False}}),
                json.dumps({"question_id": "q-3_abs", "autoeval_label": {"model": "gpt-4o-2024-08-06", "label": True}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = summarize_official_eval_results(eval_results_path=eval_results_path, ref_path=ref_path)

    assert summary["overall_accuracy"] == 0.6667
    assert summary["task_averaged_accuracy"] == 0.6667
    assert summary["abstention_accuracy"] == 1.0
    assert summary["task_metrics"]["multi-session"] == {"accuracy": 1.0, "count": 1}
    assert summary["task_metrics"]["knowledge-update"] == {"accuracy": 0.0, "count": 1}


def test_run_official_evaluation_executes_official_script_and_writes_summary(tmp_path) -> None:
    output_root = tmp_path / "outputs"
    run_dir = output_root / "longmemeval" / "oracle-backend"
    run_dir.mkdir(parents=True)
    predictions_path = run_dir / "predictions.jsonl"
    predictions_path.write_text(json.dumps({"question_id": "q-1", "hypothesis": "Sushi"}) + "\n", encoding="utf-8")

    ref_path = tmp_path / "oracle.json"
    ref_path.write_text(json.dumps([{"question_id": "q-1", "question_type": "multi-session"}]), encoding="utf-8")

    result_path = run_dir / "predictions.jsonl.eval-results-gpt-4o"
    calls: list[list[str]] = []

    def fake_run(cmd: list[str]) -> None:
        calls.append(cmd)
        result_path.write_text(
            json.dumps({"question_id": "q-1", "autoeval_label": {"model": "gpt-4o-2024-08-06", "label": True}})
            + "\n",
            encoding="utf-8",
        )

    artifacts = run_official_evaluation(
        longmemeval_root=tmp_path / "LongMemEval",
        dataset_path=ref_path,
        output_root=output_root,
        run_id="oracle-backend",
        judge_model="gpt-4o",
        python_bin="python3",
        runner=fake_run,
    )

    assert calls == [
        [
            "python3",
            str(tmp_path / "LongMemEval" / "src" / "evaluation" / "evaluate_qa.py"),
            "gpt-4o",
            str(predictions_path),
            str(ref_path),
        ]
    ]
    assert artifacts.eval_results_path == result_path
    assert artifacts.summary_path.read_text(encoding="utf-8").strip().startswith("{")
