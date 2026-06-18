"""Tests for LoCoMo one-shot runner."""

from __future__ import annotations

from pathlib import Path

from benchmark.locomo.run_all import parse_args, run_locomo_pipeline


def test_run_all_passes_qa_limit_to_replay_and_query(tmp_path) -> None:
    calls: list[tuple[str, int | None]] = []

    def replay_runner(**kwargs):
        calls.append(("replay", kwargs["qa_limit"]))

    def query_runner(**kwargs):
        calls.append(("query", kwargs["qa_limit"]))
        run_dir = tmp_path / "locomo" / "run-1"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "summary.json").write_text('{"total_questions": 2}\n', encoding="utf-8")

    summary = run_locomo_pipeline(
        dataset_path=Path("/tmp/locomo.json"),
        output_root=tmp_path,
        run_id="run-1",
        backend_url="http://127.0.0.1:8000",
        qa_limit=2,
        replay_runner=replay_runner,
        query_runner=query_runner,
    )

    assert calls == [("replay", 2), ("query", 2)]
    assert summary["summary"]["total_questions"] == 2


def test_parse_args_accepts_qa_limit() -> None:
    args = parse_args(["--output-root", "/tmp/out", "--qa-limit", "10"])

    assert args.qa_limit == 10
