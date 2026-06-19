"""Tests for LoCoMo LLM judge scoring."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from benchmark.common.io import write_jsonl
from benchmark.locomo.llm_judge import (
    LoCoMoJudgeDecision,
    build_judge_prompt,
    parse_judge_decision,
    run_llm_judge_evaluation,
)


@dataclass
class FakeJudgeClient:
    decisions: list[LoCoMoJudgeDecision]

    def __post_init__(self) -> None:
        self.prompts: list[str] = []

    async def judge(self, prompt: str) -> LoCoMoJudgeDecision:
        self.prompts.append(prompt)
        return self.decisions[len(self.prompts) - 1]


def test_llm_judge_scores_rows_and_updates_existing_summary(tmp_path: Path) -> None:
    run_dir = tmp_path / "locomo" / "run-1"
    run_dir.mkdir(parents=True)
    predictions_path = write_jsonl(
        run_dir / "predictions_with_trace.jsonl",
        [
            {
                "question_id": "conv-test:qa-1",
                "category": 2,
                "category_label": "temporal",
                "question": "When did Melanie paint a sunrise?",
                "expected_answer": "2022",
                "hypothesis": "last year",
            },
            {
                "question_id": "conv-test:qa-2",
                "category": 5,
                "category_label": "adversarial",
                "question": "What city did Melanie move to?",
                "expected_answer": "Paris",
                "hypothesis": "No information available",
            },
        ],
    )
    (run_dir / "summary.json").write_text(
        json.dumps({"total_questions": 2, "overall_f1": 0.0}) + "\n",
        encoding="utf-8",
    )
    client = FakeJudgeClient(
        decisions=[
            LoCoMoJudgeDecision(label=True, reasoning="Relative and absolute year match."),
        ]
    )

    artifacts = asyncio.run(
        run_llm_judge_evaluation(
            predictions_with_trace_path=predictions_path,
            output_dir=run_dir,
            judge_client=client,
            judge_model="fake-judge",
        )
    )

    assert "relative time references" in client.prompts[0]
    result_rows = [
        json.loads(line) for line in artifacts.results_path.read_text(encoding="utf-8").splitlines()
    ]
    assert result_rows == [
        {
            "question_id": "conv-test:qa-1",
            "category": 2,
            "category_label": "temporal",
            "question": "When did Melanie paint a sunrise?",
            "expected_answer": "2022",
            "hypothesis": "last year",
            "llm_judge": {
                "model": "fake-judge",
                "label": True,
                "score": 1,
                "reasoning": "Relative and absolute year match.",
            },
        }
    ]
    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["status"] == "ready"
    assert summary["llm_judge_score"] == 1.0
    assert summary["category_metrics"]["2"] == {
        "label": "temporal",
        "llm_judge_score": 1.0,
        "count": 1,
    }
    updated_summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert updated_summary["llm_judge_score"] == 1.0
    assert updated_summary["llm_judge"]["evaluated_questions"] == 1


def test_judge_prompt_keeps_mem0_style_date_tolerance() -> None:
    prompt = build_judge_prompt(
        question="When did Melanie paint a sunrise?",
        gold_answer="2022",
        generated_answer="last year",
        category=2,
    )

    assert 'Converting "last year" to the actual year' in prompt
    assert "Return JSON" in prompt


def test_llm_judge_skips_without_api_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    run_dir = tmp_path / "locomo" / "run-1"
    run_dir.mkdir(parents=True)
    predictions_path = write_jsonl(
        run_dir / "predictions_with_trace.jsonl",
        [
            {
                "question_id": "conv-test:qa-1",
                "category": 2,
                "question": "When did Melanie paint a sunrise?",
                "expected_answer": "2022",
                "hypothesis": "last year",
            }
        ],
    )

    artifacts = asyncio.run(
        run_llm_judge_evaluation(
            predictions_with_trace_path=predictions_path,
            output_dir=run_dir,
            judge_model="fake-judge",
        )
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["status"] == "skipped"
    assert summary["reason"] == "OPENAI_API_KEY is not set"


def test_parse_judge_decision_accepts_json_and_plain_labels() -> None:
    assert parse_judge_decision('{"label":"CORRECT","reasoning":"same"}').label is True
    assert parse_judge_decision("WRONG").label is False
    assert parse_judge_decision({"label": True, "reasoning": "ok"}).reasoning == "ok"
