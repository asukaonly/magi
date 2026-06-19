"""Tests for LoCoMo one-shot runner."""

from __future__ import annotations

from pathlib import Path

from benchmark.locomo.run_all import parse_args, run_locomo_pipeline


def test_run_all_passes_qa_limit_to_replay_and_query(tmp_path) -> None:
    calls: list[tuple[str, int | None, str | None]] = []

    def replay_runner(**kwargs):
        calls.append(("replay", kwargs["qa_limit"], kwargs["backend_url"]))

    def query_runner(**kwargs):
        calls.append(("query", kwargs["qa_limit"], kwargs["backend_url"]))
        run_dir = tmp_path / "locomo" / "run-1"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "summary.json").write_text('{"total_questions": 2}\n', encoding="utf-8")
        (run_dir / "predictions_with_trace.jsonl").write_text(
            (
                '{"question_id":"conv-test:qa-1","sample_id":"conv-test",'
                '"qa_index":0,"category":4,"category_label":"single-hop",'
                '"question":"What did Caroline join?","expected_answer":"support group",'
                '"evidence":["D1:1"],"answer_session_ids":["session_1"],'
                '"hypothesis":"unknown","retrieved_session_ids":["session_2"],'
                '"retrieved_turn_ids":["D2:1"]}\n'
            ),
            encoding="utf-8",
        )

    def judge_runner(**kwargs):
        calls.append(("judge", kwargs["qa_limit"], kwargs["backend_url"]))
        run_dir = tmp_path / "locomo" / "run-1"
        (run_dir / "llm_judge_summary.json").write_text(
            '{"status":"ready","llm_judge_score":1.0,"evaluated_questions":1}\n',
            encoding="utf-8",
        )
        (run_dir / "summary.json").write_text(
            '{"total_questions":2,"llm_judge_score":1.0}\n',
            encoding="utf-8",
        )

    summary = run_locomo_pipeline(
        dataset_path=Path("/tmp/locomo.json"),
        output_root=tmp_path,
        run_id="run-1",
        backend_url="http://127.0.0.1:8000",
        qa_limit=2,
        replay_runner=replay_runner,
        query_runner=query_runner,
        judge_runner=judge_runner,
    )

    assert calls == [
        ("replay", 2, "http://127.0.0.1:8000"),
        ("query", 2, "http://127.0.0.1:8000"),
        ("judge", 2, "http://127.0.0.1:8000"),
    ]
    assert summary["summary"]["total_questions"] == 2
    assert summary["summary"]["llm_judge_score"] == 1.0
    assert summary["llm_judge"]["llm_judge_score"] == 1.0
    assert summary["error_report"]["non_perfect_question_count"] == 1
    assert (tmp_path / "locomo" / "run-1" / "error_report.jsonl").exists()


def test_parse_args_accepts_qa_limit_and_judge_options() -> None:
    args = parse_args(
        [
            "--output-root",
            "/tmp/out",
            "--qa-limit",
            "10",
            "--backend-url",
            "http://127.0.0.1:8000",
            "--skip-llm-judge",
        ]
    )

    assert args.qa_limit == 10
    assert args.backend_url == "http://127.0.0.1:8000"
    assert args.skip_llm_judge is True
