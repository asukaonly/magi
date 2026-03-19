"""Tests for the one-shot LongMemEval runner."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from benchmark.longmemeval.run_all import (
    DEFAULT_BACKEND_URL,
    DEFAULT_LONGMEMEVAL_ROOT,
    format_run_id,
    resolve_longmemeval_root,
    run_longmemeval_pipeline,
)


def test_format_run_id_uses_readable_timestamp() -> None:
    value = format_run_id(datetime(2026, 3, 19, 18, 5, 7))
    assert value == "2026-03-19 18:05:07"


def test_resolve_longmemeval_root_prefers_env_value(monkeypatch, tmp_path) -> None:
    custom_root = tmp_path / "LongMemEval"
    custom_root.mkdir()
    monkeypatch.setenv("LONGMEMEVAL_ROOT", str(custom_root))

    assert resolve_longmemeval_root() == custom_root


def test_resolve_longmemeval_root_falls_back_to_default(monkeypatch, tmp_path) -> None:
    default_root = tmp_path / "LongMemEval"
    default_root.mkdir()
    monkeypatch.delenv("LONGMEMEVAL_ROOT", raising=False)
    monkeypatch.setattr("benchmark.longmemeval.run_all.DEFAULT_LONGMEMEVAL_ROOT", default_root)

    assert resolve_longmemeval_root() == default_root


def test_run_all_executes_replay_query_and_official_eval_in_order(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    calls: list[tuple[str, dict[str, object]]] = []
    output_root = tmp_path / "outputs"
    run_id = "2026-03-19 18:05:07"
    run_dir = output_root / "longmemeval" / "2026-03-19_18_05_07"
    run_dir.mkdir(parents=True, exist_ok=True)

    def fake_replay(**kwargs):
        calls.append(("replay", kwargs))
        (run_dir / "replay_manifest.jsonl").write_text("", encoding="utf-8")
        (run_dir / "post_replay.json").write_text("{}", encoding="utf-8")

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

    summary = run_longmemeval_pipeline(
        dataset_path=tmp_path / "oracle.json",
        output_root=output_root,
        run_id=run_id,
        replay_runner=fake_replay,
        query_runner=fake_query,
        official_eval_runner=fake_eval,
        longmemeval_root=tmp_path / "LongMemEval",
    )

    assert [name for name, _ in calls] == ["replay", "query", "eval"]
    assert calls[0][1]["backend_url"] == DEFAULT_BACKEND_URL
    assert calls[1][1]["backend_url"] == DEFAULT_BACKEND_URL
    assert calls[2][1]["run_id"] == run_id
    assert summary["run_id"] == run_id
    assert summary["run_dir"] == str(run_dir)
    assert summary["backend_url"] == DEFAULT_BACKEND_URL
    assert summary["official_eval"]["overall_accuracy"] == 0.8


def test_run_all_skips_official_eval_when_openai_key_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    calls: list[str] = []

    def fake_replay(**kwargs):
        calls.append("replay")

    def fake_query(**kwargs):
        calls.append("query")

    summary = run_longmemeval_pipeline(
        dataset_path=tmp_path / "oracle.json",
        output_root=tmp_path / "outputs",
        run_id="2026-03-19 18:05:07",
        replay_runner=fake_replay,
        query_runner=fake_query,
        official_eval_runner=lambda **kwargs: (_ for _ in ()).throw(AssertionError("should not run")),
        longmemeval_root=tmp_path / "LongMemEval",
    )

    assert calls == ["replay", "query"]
    assert summary["official_eval"]["status"] == "skipped"
    assert "OPENAI_API_KEY" in summary["official_eval"]["reason"]
