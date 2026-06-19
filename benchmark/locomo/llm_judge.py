"""LLM-as-judge evaluation for LoCoMo predictions."""

from __future__ import annotations

# ruff: noqa: E402

import argparse
import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmark.common.io import read_jsonl, write_jsonl
from benchmark.common.paths import build_run_output_dir
from benchmark.locomo.adapter import CATEGORY_LABELS

DEFAULT_JUDGE_MODEL = os.getenv("LOCOMO_JUDGE_MODEL", "gpt-4o-mini")
DEFAULT_SCORE_CATEGORIES = (1, 2, 3, 4)

JUDGE_SYSTEM_PROMPT = "You are evaluating conversational AI memory recall. Return JSON only."

JUDGE_PROMPT_TEMPLATE = """Label the generated answer as CORRECT or WRONG.

The question asks about something one conversation participant should know from prior conversations.

Rules:
1. Paraphrases count as CORRECT when they refer to the same fact, person, object, event, preference, or idea.
2. Extra detail is fine if the answer still includes the key fact from the gold answer.
3. Partial list answers are CORRECT if they include at least one correct gold item. Only mark WRONG when none of the gold items are present.
4. Date and time formats are flexible: relative time references can match absolute dates when they refer to the same time period. Converting "last year" to the actual year, such as 2022 for a 2023 conversation, is CORRECT.
5. For temporal answers, tolerate equivalent dates, months, years, and nearby natural-language descriptions when they clearly identify the same time.
6. Focus on remembered knowledge, not exact wording. Minor wording, specificity, or formatting differences should not make an otherwise correct answer wrong.

Only mark WRONG if the generated answer is about a different fact, contradicts the gold answer, or contains no correct item from the gold answer.

Question: {question}
Gold answer: {gold_answer}
Generated answer: {generated_answer}

Return JSON with exactly:
{{"reasoning": "one short sentence", "label": "CORRECT"}}
or
{{"reasoning": "one short sentence", "label": "WRONG"}}
"""


@dataclass(slots=True)
class LoCoMoJudgeDecision:
    """Parsed LLM judge decision."""

    label: bool
    reasoning: str = ""
    raw: Any = None
    error: str | None = None


class SupportsLoCoMoJudgeClient(Protocol):
    """Small async protocol for LLM judge clients."""

    async def judge(self, prompt: str) -> LoCoMoJudgeDecision:
        """Judge a formatted LoCoMo prompt."""


@dataclass(slots=True)
class LoCoMoJudgeArtifacts:
    """Files produced by LoCoMo LLM judge evaluation."""

    predictions_with_trace_path: Path
    results_path: Path
    predictions_with_judge_path: Path
    summary_path: Path


class OpenAIChatJudgeClient:
    """OpenAI-compatible chat client for LoCoMo LLM judge scoring."""

    def __init__(
        self,
        *,
        judge_model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        from openai import AsyncOpenAI, Timeout

        client_kwargs: dict[str, Any] = {
            "api_key": api_key or os.getenv("OPENAI_API_KEY"),
            "timeout": Timeout(timeout_seconds, connect=10.0),
        }
        resolved_base_url = base_url or os.getenv("OPENAI_BASE_URL")
        if resolved_base_url:
            client_kwargs["base_url"] = resolved_base_url
        self._client = AsyncOpenAI(**client_kwargs)
        self._judge_model = judge_model

    async def judge(self, prompt: str) -> LoCoMoJudgeDecision:
        kwargs: dict[str, Any] = {
            "model": self._judge_model,
            "messages": [
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            **_openai_token_limit_kwargs(self._judge_model, 512),
            **_openai_temperature_kwargs(self._judge_model, 0.0),
        }
        response = await self._client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content or ""
        return parse_judge_decision(content)


def build_judge_prompt(
    *,
    question: str,
    gold_answer: str,
    generated_answer: str,
    category: int,
) -> str:
    """Build a LoCoMo judge prompt using common Mem0/Memobase-style rules."""
    return JUDGE_PROMPT_TEMPLATE.format(
        question=str(question or "").strip(),
        gold_answer=str(gold_answer or "").strip(),
        generated_answer=str(generated_answer or "").strip(),
        category=int(category or 0),
    )


def parse_judge_decision(raw: Any) -> LoCoMoJudgeDecision:
    """Parse a JSON or plain-text judge response into a boolean decision."""
    if isinstance(raw, LoCoMoJudgeDecision):
        return raw
    if isinstance(raw, dict):
        return _decision_from_mapping(raw, raw=raw)

    text = str(raw or "").strip()
    if not text:
        return LoCoMoJudgeDecision(label=False, raw=raw, error="empty judge response")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return _decision_from_mapping(parsed, raw=raw)

    normalized = text.upper()
    has_correct = bool(re.search(r"\bCORRECT\b", normalized))
    has_wrong = bool(re.search(r"\bWRONG\b", normalized))
    if has_correct and not has_wrong:
        return LoCoMoJudgeDecision(label=True, reasoning=text, raw=raw)
    if has_wrong and not has_correct:
        return LoCoMoJudgeDecision(label=False, reasoning=text, raw=raw)
    return LoCoMoJudgeDecision(
        label=False,
        reasoning=text,
        raw=raw,
        error="could not parse unique judge label",
    )


async def run_llm_judge_evaluation(
    *,
    predictions_with_trace_path: str | Path,
    output_dir: str | Path | None = None,
    judge_client: SupportsLoCoMoJudgeClient | None = None,
    judge_model: str = DEFAULT_JUDGE_MODEL,
    score_categories: Sequence[int] = DEFAULT_SCORE_CATEGORIES,
    max_concurrency: int = 4,
    timeout_seconds: float = 120.0,
    base_url: str | None = None,
) -> LoCoMoJudgeArtifacts:
    """Judge LoCoMo predictions and merge the aggregate score into summary.json."""
    predictions_path = Path(predictions_with_trace_path)
    resolved_output_dir = Path(output_dir) if output_dir is not None else predictions_path.parent
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    results_path = resolved_output_dir / "llm_judge_results.jsonl"
    predictions_with_judge_path = resolved_output_dir / "predictions_with_judge.jsonl"
    summary_path = resolved_output_dir / "llm_judge_summary.json"

    api_key = os.getenv("OPENAI_API_KEY")
    if judge_client is None and not api_key:
        summary = {
            "status": "skipped",
            "reason": "OPENAI_API_KEY is not set",
            "judge_model": judge_model,
            "score_categories": [int(category) for category in score_categories],
            "evaluated_questions": 0,
        }
        write_jsonl(results_path, [])
        write_jsonl(predictions_with_judge_path, read_jsonl(predictions_path))
        _write_summary(summary_path, summary)
        _merge_into_run_summary(resolved_output_dir, summary)
        return LoCoMoJudgeArtifacts(
            predictions_with_trace_path=predictions_path,
            results_path=results_path,
            predictions_with_judge_path=predictions_with_judge_path,
            summary_path=summary_path,
        )

    resolved_judge = judge_client or OpenAIChatJudgeClient(
        judge_model=judge_model,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
    )
    rows = read_jsonl(predictions_path)
    score_category_set = {int(category) for category in score_categories}
    scoreable_rows = [row for row in rows if int(row.get("category") or 0) in score_category_set]

    semaphore = asyncio.Semaphore(max(1, int(max_concurrency or 1)))

    async def judge_row(row: dict[str, Any]) -> dict[str, Any]:
        prompt = build_judge_prompt(
            question=str(row.get("question") or ""),
            gold_answer=str(row.get("expected_answer") or ""),
            generated_answer=str(row.get("hypothesis") or ""),
            category=int(row.get("category") or 0),
        )
        async with semaphore:
            try:
                decision = await resolved_judge.judge(prompt)
            except Exception as exc:
                decision = LoCoMoJudgeDecision(
                    label=False,
                    reasoning="",
                    error=f"{type(exc).__name__}: {exc}",
                )
        score = 1 if decision.label else 0
        payload = {
            "question_id": str(row.get("question_id") or ""),
            "category": int(row.get("category") or 0),
            "category_label": str(row.get("category_label") or ""),
            "question": str(row.get("question") or ""),
            "expected_answer": str(row.get("expected_answer") or ""),
            "hypothesis": str(row.get("hypothesis") or ""),
            "llm_judge": {
                "model": judge_model,
                "label": bool(decision.label),
                "score": score,
                "reasoning": decision.reasoning,
            },
        }
        if decision.error:
            payload["llm_judge"]["error"] = decision.error
        return payload

    judged_rows = list(await asyncio.gather(*(judge_row(row) for row in scoreable_rows)))
    judged_by_qid = {str(row.get("question_id") or ""): row["llm_judge"] for row in judged_rows}
    rows_with_judge: list[dict[str, Any]] = []
    for row in rows:
        copied = dict(row)
        qid = str(copied.get("question_id") or "")
        if qid in judged_by_qid:
            copied["llm_judge"] = judged_by_qid[qid]
        rows_with_judge.append(copied)

    write_jsonl(results_path, judged_rows)
    write_jsonl(predictions_with_judge_path, rows_with_judge)
    summary = summarize_llm_judge_results(
        judged_rows,
        judge_model=judge_model,
        score_categories=score_categories,
    )
    _write_summary(summary_path, summary)
    _merge_into_run_summary(resolved_output_dir, summary)
    return LoCoMoJudgeArtifacts(
        predictions_with_trace_path=predictions_path,
        results_path=results_path,
        predictions_with_judge_path=predictions_with_judge_path,
        summary_path=summary_path,
    )


def summarize_llm_judge_results(
    rows: Sequence[dict[str, Any]],
    *,
    judge_model: str,
    score_categories: Sequence[int],
) -> dict[str, Any]:
    """Aggregate per-question LoCoMo judge rows."""
    scores: list[int] = []
    errors = 0
    by_category: dict[int, list[int]] = {}
    for row in rows:
        category = int(row.get("category") or 0)
        judge = row.get("llm_judge") or {}
        score = int(judge.get("score") or 0)
        scores.append(score)
        by_category.setdefault(category, []).append(score)
        if judge.get("error"):
            errors += 1

    category_metrics = {
        str(category): {
            "label": CATEGORY_LABELS.get(category, f"category-{category}"),
            "llm_judge_score": _round4(sum(values) / len(values)),
            "count": len(values),
        }
        for category, values in sorted(by_category.items())
    }
    return {
        "status": "ready",
        "judge_model": judge_model,
        "score_categories": [int(category) for category in score_categories],
        "evaluated_questions": len(rows),
        "correct": int(sum(scores)),
        "errors": errors,
        "llm_judge_score": _round4(sum(scores) / len(scores)) if scores else 0.0,
        "category_metrics": category_metrics,
    }


def build_predictions_path(*, output_root: str | Path, run_id: str) -> Path:
    """Return the default predictions_with_trace path for a LoCoMo run."""
    return (
        build_run_output_dir(
            root_dir=output_root,
            benchmark_name="locomo",
            run_id=run_id,
        )
        / "predictions_with_trace.jsonl"
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run LLM-as-judge scoring for a LoCoMo benchmark run."
    )
    parser.add_argument(
        "--predictions-with-trace", default=None, help="Explicit predictions_with_trace.jsonl path."
    )
    parser.add_argument(
        "--output-root", default="benchmark/outputs", help="Directory containing benchmark outputs."
    )
    parser.add_argument("--run-id", default=None, help="Run identifier used with --output-root.")
    parser.add_argument(
        "--judge-model", default=DEFAULT_JUDGE_MODEL, help="OpenAI-compatible judge model."
    )
    parser.add_argument(
        "--judge-base-url", default=None, help="Optional OpenAI-compatible base URL."
    )
    parser.add_argument(
        "--judge-concurrency", type=int, default=4, help="Maximum concurrent judge requests."
    )
    parser.add_argument(
        "--request-timeout", type=float, default=120.0, help="Judge request timeout in seconds."
    )
    parser.add_argument(
        "--include-adversarial",
        action="store_true",
        help="Also judge LoCoMo category 5. Default follows common 1540-question scoring and excludes it.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.predictions_with_trace:
        predictions_path = Path(args.predictions_with_trace)
        output_dir = predictions_path.parent
    elif args.run_id:
        predictions_path = build_predictions_path(output_root=args.output_root, run_id=args.run_id)
        output_dir = predictions_path.parent
    else:
        raise SystemExit("--run-id or --predictions-with-trace is required")

    score_categories = (1, 2, 3, 4, 5) if args.include_adversarial else DEFAULT_SCORE_CATEGORIES
    artifacts = asyncio.run(
        run_llm_judge_evaluation(
            predictions_with_trace_path=predictions_path,
            output_dir=output_dir,
            judge_model=args.judge_model,
            score_categories=score_categories,
            max_concurrency=args.judge_concurrency,
            timeout_seconds=args.request_timeout,
            base_url=args.judge_base_url,
        )
    )
    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    print(f"Wrote {artifacts.results_path}")
    print(f"Wrote {artifacts.predictions_with_judge_path}")
    print(f"Wrote {artifacts.summary_path}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _decision_from_mapping(data: dict[str, Any], *, raw: Any) -> LoCoMoJudgeDecision:
    label = data.get("label", data.get("correct"))
    if isinstance(label, bool):
        parsed_label = label
    elif isinstance(label, (int, float)):
        parsed_label = bool(label)
    else:
        label_text = str(label or "").strip().upper()
        parsed_label = label_text in {"CORRECT", "YES", "TRUE", "1"}
    return LoCoMoJudgeDecision(
        label=parsed_label,
        reasoning=str(data.get("reasoning") or data.get("reason") or ""),
        raw=raw,
        error=str(data.get("error")) if data.get("error") else None,
    )


def _merge_into_run_summary(output_dir: Path, judge_summary: dict[str, Any]) -> None:
    summary_path = output_dir / "summary.json"
    existing: dict[str, Any] = {}
    if summary_path.exists():
        try:
            existing = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    existing["llm_judge"] = judge_summary
    if judge_summary.get("status") == "ready":
        existing["llm_judge_score"] = judge_summary.get("llm_judge_score", 0.0)
    summary_path.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _write_summary(path: Path, summary: dict[str, Any]) -> None:
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _openai_token_limit_kwargs(model: str, max_tokens: int) -> dict[str, Any]:
    lowered = str(model or "").lower()
    if lowered.startswith(("gpt-5", "o1", "o3", "o4")):
        return {"max_completion_tokens": max_tokens}
    return {"max_tokens": max_tokens}


def _openai_temperature_kwargs(model: str, temperature: float) -> dict[str, Any]:
    lowered = str(model or "").lower()
    if lowered.startswith(("gpt-5", "o1", "o3", "o4")):
        return {}
    return {"temperature": temperature}


def _round4(value: float) -> float:
    return round(float(value), 4)


if __name__ == "__main__":
    raise SystemExit(main())
