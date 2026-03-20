"""Tests for rerunning LongMemEval query and scoring without replay."""

from __future__ import annotations

import json

from benchmark.longmemeval.rerun_query_and_score import (
    DEFAULT_BACKEND_URL,
    run_query_and_score_pipeline,
)


def test_rerun_query_and_score_executes_query_then_official_eval(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    calls: list[tuple[str, dict[str, object]]] = []
    output_root = tmp_path / "outputs"
    run_id = "2026-03-19 20:03:28"
    run_dir = output_root / "longmemeval" / "2026-03-19_20_03_28"
    run_dir.mkdir(parents=True, exist_ok=True)

    def fake_query(**kwargs):
        calls.append(("query", kwargs))
        (run_dir / "predictions.jsonl").write_text(
            json.dumps({"question_id": "q-1", "hypothesis": "Sushi"}) + "\n",
            encoding="utf-8",
        )
        (run_dir / "summary.json").write_text(
            json.dumps({"session_recall_at_k": 1.0}),
            encoding="utf-8",
        )

    def fake_eval(**kwargs):
        calls.append(("eval", kwargs))
        summary_path = run_dir / "official_eval_summary.json"
        summary_path.write_text(
            json.dumps({"overall_accuracy": 0.8, "task_averaged_accuracy": 0.75}),
            encoding="utf-8",
        )
        return type(
            "Artifacts",
            (),
            {
                "predictions_path": run_dir / "predictions.jsonl",
                "eval_results_path": run_dir / "predictions.jsonl.eval-results-gpt-4o",
                "summary_path": summary_path,
            },
        )()

    summary = run_query_and_score_pipeline(
        dataset_path=tmp_path / "oracle.json",
        output_root=output_root,
        run_id=run_id,
        answer_with_llm=True,
        query_runner=fake_query,
        official_eval_runner=fake_eval,
        longmemeval_root=tmp_path / "LongMemEval",
    )

    assert [name for name, _ in calls] == ["query", "eval"]
    assert calls[0][1]["backend_url"] == DEFAULT_BACKEND_URL
    assert calls[0][1]["answer_with_llm"] is True
    assert calls[1][1]["run_id"] == run_id
    assert summary["run_id"] == run_id
    assert summary["run_dir"] == str(run_dir)
    assert summary["backend_url"] == DEFAULT_BACKEND_URL
    assert summary["official_eval"]["overall_accuracy"] == 0.8


def test_rerun_query_and_score_passes_explicit_mode(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_query(**kwargs):
        calls.append(("query", kwargs))

    summary = run_query_and_score_pipeline(
        dataset_path=tmp_path / "oracle.json",
        output_root=tmp_path / "outputs",
        run_id="2026-03-19 20:03:28",
        mode="detail",
        query_runner=fake_query,
        official_eval_runner=lambda **kwargs: (_ for _ in ()).throw(AssertionError("should not run")),
        longmemeval_root=tmp_path / "LongMemEval",
    )

    assert calls == [("query", {"dataset_path": tmp_path / "oracle.json", "output_root": tmp_path / "outputs", "run_id": "2026-03-19 20:03:28", "backend_url": DEFAULT_BACKEND_URL, "answer_with_llm": False, "mode": "detail"})]
    assert summary["official_eval"]["status"] == "skipped"


def test_rerun_query_and_score_skips_official_eval_when_openai_key_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    calls: list[str] = []

    def fake_query(**kwargs):
        calls.append("query")

    summary = run_query_and_score_pipeline(
        dataset_path=tmp_path / "oracle.json",
        output_root=tmp_path / "outputs",
        run_id="2026-03-19 20:03:28",
        query_runner=fake_query,
        official_eval_runner=lambda **kwargs: (_ for _ in ()).throw(AssertionError("should not run")),
        longmemeval_root=tmp_path / "LongMemEval",
    )

    assert calls == ["query"]
    assert summary["official_eval"]["status"] == "skipped"
    assert "OPENAI_API_KEY" in summary["official_eval"]["reason"]
