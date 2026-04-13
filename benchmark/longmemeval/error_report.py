"""Analyze LongMemEval wrong answers into retrieval and synthesis buckets."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = REPO_ROOT / "backend" / "src"
for candidate in (REPO_ROOT, BACKEND_SRC):
    candidate_text = str(candidate)
    if candidate_text not in sys.path:
        sys.path.insert(0, candidate_text)

from benchmark.common.io import read_jsonl, write_jsonl
from benchmark.common.paths import build_run_output_dir


TURN_ID_RE = re.compile(r"^(.*):turn-(\d+)$")
CSV_COLUMNS = [
    "question_id",
    "question_type",
    "primary_bucket",
    "secondary_bucket",
    "question",
    "expected_answer",
    "hypothesis",
    "gold_turn_in_bundle",
    "gold_session_in_top5",
    "all_gold_sessions_in_top5",
    "bundle_window",
    "gold_session_ids",
    "retrieved_session_ids",
    "gold_turn_ids",
    "retrieved_turn_ids",
]


@dataclass(slots=True)
class ErrorAnalysisReport:
    """Structured error report for a LongMemEval run."""

    rows: list[dict[str, Any]]
    summary: dict[str, Any]


@dataclass(slots=True)
class ErrorReportArtifacts:
    """Files written by the error analysis exporter."""

    csv_path: Path
    jsonl_path: Path
    summary_path: Path


def analyze_prediction_errors(
    *,
    references: Sequence[Mapping[str, Any]],
    predictions: Sequence[Mapping[str, Any]],
    eval_rows: Sequence[Mapping[str, Any]],
    top_k: int = 5,
) -> ErrorAnalysisReport:
    """Bucket wrong answers by retrieval miss, bundle miss, and synthesis miss."""
    ref_by_qid = {str(row.get("question_id") or ""): dict(row) for row in references}
    eval_by_qid = {str(row.get("question_id") or ""): dict(row) for row in eval_rows}
    wrong_rows: list[dict[str, Any]] = []

    primary_buckets: Counter[str] = Counter()
    secondary_buckets: Counter[str] = Counter()
    by_question_type: dict[str, Counter[str]] = defaultdict(Counter)
    meta = Counter()

    for prediction in predictions:
        question_id = str(prediction.get("question_id") or "")
        if not question_id:
            continue
        if bool((prediction.get("metadata") or {}).get("is_abstention", False)):
            continue

        eval_row = eval_by_qid.get(question_id)
        if bool((eval_row or {}).get("autoeval_label", {}).get("label", False)):
            continue

        reference = ref_by_qid.get(question_id)
        if reference is None:
            continue

        question = str(reference.get("question") or "")
        question_type = str(reference.get("question_type") or prediction.get("question_type") or "")
        expected_answer = str(reference.get("answer") or prediction.get("expected_answer") or "")
        hypothesis = str(prediction.get("hypothesis") or "")
        gold_session_ids = _to_clean_str_list(prediction.get("answer_session_ids") or [])
        retrieved_session_ids = _to_clean_str_list(prediction.get("retrieved_session_ids") or [])
        retrieved_turn_ids = _to_clean_str_list(prediction.get("retrieved_turn_ids") or [])
        gold_turns = _extract_gold_turns(reference)

        bundle_window = _bundle_neighbor_window(question)
        gold_turn_in_bundle, covered_gold_turn_ids = _gold_turn_in_bundle(
            gold_turns=gold_turns,
            retrieved_turn_ids=retrieved_turn_ids,
            bundle_window=bundle_window,
        )
        gold_session_in_topk = bool(set(gold_session_ids) & set(retrieved_session_ids[:top_k]))
        all_gold_sessions_in_topk = bool(gold_session_ids) and set(gold_session_ids).issubset(
            set(retrieved_session_ids[:top_k])
        )
        gold_session_retrieved = bool(set(gold_session_ids) & set(retrieved_session_ids))

        if gold_session_in_topk:
            meta["wrong_but_topk_session_any"] += 1
        if all_gold_sessions_in_topk:
            meta["wrong_but_topk_session_all"] += 1
        if gold_turn_in_bundle:
            meta["wrong_but_gold_turn_likely_in_bundle"] += 1

        primary_bucket, secondary_bucket = _classify_error(
            question=question,
            question_type=question_type,
            expected_answer=expected_answer,
            hypothesis=hypothesis,
            gold_session_ids=gold_session_ids,
            retrieved_session_ids=retrieved_session_ids,
            gold_session_retrieved=gold_session_retrieved,
            gold_session_in_topk=gold_session_in_topk,
            all_gold_sessions_in_topk=all_gold_sessions_in_topk,
            gold_turn_in_bundle=gold_turn_in_bundle,
        )

        row = {
            "question_id": question_id,
            "question_type": question_type,
            "primary_bucket": primary_bucket,
            "secondary_bucket": secondary_bucket,
            "question": question,
            "expected_answer": expected_answer,
            "hypothesis": hypothesis,
            "gold_turn_in_bundle": gold_turn_in_bundle,
            "gold_session_in_top5": gold_session_in_topk,
            "all_gold_sessions_in_top5": all_gold_sessions_in_topk,
            "bundle_window": bundle_window,
            "gold_session_ids": gold_session_ids,
            "retrieved_session_ids": retrieved_session_ids,
            "gold_turn_ids": [turn_id for turn_id, _, _ in gold_turns],
            "covered_gold_turn_ids": covered_gold_turn_ids,
            "retrieved_turn_ids": retrieved_turn_ids,
        }
        wrong_rows.append(row)
        primary_buckets[primary_bucket] += 1
        secondary_buckets[secondary_bucket] += 1
        by_question_type[question_type][primary_bucket] += 1

    summary = _build_summary(
        wrong_rows=wrong_rows,
        primary_buckets=primary_buckets,
        secondary_buckets=secondary_buckets,
        by_question_type=by_question_type,
        meta=meta,
        top_k=top_k,
    )
    return ErrorAnalysisReport(rows=wrong_rows, summary=summary)


def export_error_report(output_dir: str | Path, report: ErrorAnalysisReport) -> ErrorReportArtifacts:
    """Write error analysis tables as CSV, JSONL, and summary JSON."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    jsonl_rows = [_serialize_row(row) for row in report.rows]
    jsonl_path = write_jsonl(output_path / "error_report.jsonl", jsonl_rows)

    csv_path = output_path / "error_report.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in jsonl_rows:
            writer.writerow({key: row.get(key, "") for key in CSV_COLUMNS})

    summary_path = output_path / "error_report_summary.json"
    summary_path.write_text(
        json.dumps(report.summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return ErrorReportArtifacts(
        csv_path=csv_path,
        jsonl_path=jsonl_path,
        summary_path=summary_path,
    )


def run_error_analysis(
    *,
    dataset_path: str | Path,
    predictions_with_trace_path: str | Path,
    eval_results_path: str | Path,
    output_dir: str | Path,
    top_k: int = 5,
) -> ErrorReportArtifacts:
    """Load run artifacts, analyze wrong answers, and export a report."""
    references = _load_json_or_jsonl(dataset_path)
    predictions = read_jsonl(predictions_with_trace_path)
    eval_rows = read_jsonl(eval_results_path)
    report = analyze_prediction_errors(
        references=references,
        predictions=predictions,
        eval_rows=eval_rows,
        top_k=top_k,
    )
    return export_error_report(output_dir, report)


def build_default_paths(
    *,
    output_root: str | Path,
    run_id: str,
    judge_model: str,
) -> tuple[Path, Path, Path]:
    """Resolve default file locations for an existing LongMemEval run."""
    run_dir = build_run_output_dir(
        root_dir=output_root,
        benchmark_name="longmemeval",
        run_id=run_id,
    )
    predictions_with_trace_path = run_dir / "predictions_with_trace.jsonl"
    eval_results_path = run_dir / f"predictions.jsonl.eval-results-{judge_model}"
    return run_dir, predictions_with_trace_path, eval_results_path


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a bucketed LongMemEval wrong-answer report.")
    parser.add_argument("--dataset", required=True, help="Path to the LongMemEval dataset JSON.")
    parser.add_argument("--output-root", default="benchmark/outputs", help="Directory containing benchmark outputs.")
    parser.add_argument("--run-id", required=True, help="Benchmark run identifier.")
    parser.add_argument(
        "--judge-model",
        default="gpt-4o",
        help="Judge model suffix used in predictions.jsonl.eval-results-<judge-model>.",
    )
    parser.add_argument(
        "--predictions-with-trace",
        help="Optional explicit path to predictions_with_trace.jsonl. Overrides --output-root/--run-id.",
    )
    parser.add_argument(
        "--eval-results",
        help="Optional explicit path to predictions.jsonl.eval-results-<judge-model>. Overrides --output-root/--run-id.",
    )
    parser.add_argument("--top-k", type=int, default=5, help="Top-k session cutoff used in the summary.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    run_dir, default_predictions_path, default_eval_path = build_default_paths(
        output_root=args.output_root,
        run_id=args.run_id,
        judge_model=args.judge_model,
    )
    predictions_with_trace_path = Path(args.predictions_with_trace or default_predictions_path)
    eval_results_path = Path(args.eval_results or default_eval_path)
    artifacts = run_error_analysis(
        dataset_path=args.dataset,
        predictions_with_trace_path=predictions_with_trace_path,
        eval_results_path=eval_results_path,
        output_dir=run_dir,
        top_k=args.top_k,
    )
    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    print(f"Wrote {artifacts.csv_path}")
    print(f"Wrote {artifacts.jsonl_path}")
    print(f"Wrote {artifacts.summary_path}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _build_summary(
    *,
    wrong_rows: Sequence[Mapping[str, Any]],
    primary_buckets: Counter[str],
    secondary_buckets: Counter[str],
    by_question_type: Mapping[str, Counter[str]],
    meta: Counter[str],
    top_k: int,
) -> dict[str, Any]:
    wrong_count = len(wrong_rows)
    return {
        "wrong_question_count": wrong_count,
        "top_k": top_k,
        "primary_buckets": dict(primary_buckets),
        "primary_bucket_rates": _counter_rates(primary_buckets, wrong_count),
        "secondary_buckets": dict(secondary_buckets),
        "secondary_bucket_rates": _counter_rates(secondary_buckets, wrong_count),
        "meta": dict(meta),
        "meta_rates": _counter_rates(meta, wrong_count),
        "by_question_type": {
            question_type: {
                "wrong_count": sum(counter.values()),
                "primary_buckets": dict(counter),
            }
            for question_type, counter in by_question_type.items()
        },
    }


def _classify_error(
    *,
    question: str,
    question_type: str,
    expected_answer: str,
    hypothesis: str,
    gold_session_ids: Sequence[str],
    retrieved_session_ids: Sequence[str],
    gold_session_retrieved: bool,
    gold_session_in_topk: bool,
    all_gold_sessions_in_topk: bool,
    gold_turn_in_bundle: bool,
) -> tuple[str, str]:
    if not gold_session_retrieved:
        primary_bucket = "A. session miss"
        if question_type == "single-session-preference":
            return primary_bucket, "preference retrieval miss"
        if question_type == "multi-session":
            return primary_bucket, "multi-session retrieval miss"
        return primary_bucket, "single/temporal retrieval miss"

    if not gold_turn_in_bundle:
        primary_bucket = "B. same session, answer turn not in bundle"
        if question_type == "multi-session":
            if gold_session_in_topk and not all_gold_sessions_in_topk:
                return primary_bucket, "multi-session partial coverage"
            return primary_bucket, "multi-session turn gap"
        if question_type == "knowledge-update":
            return primary_bucket, "updated fact outside local window"
        if question_type == "single-session-preference":
            return primary_bucket, "preference evidence drift"
        if _is_aggregation_question(question):
            return primary_bucket, "aggregation operand missing"
        if _is_temporal_question(question) or question_type == "temporal-reasoning":
            return primary_bucket, "temporal anchor missing"
        return primary_bucket, "same-session local window miss"

    primary_bucket = "C. answer turn likely present, synthesis/judge miss"
    normalized_gold = _normalize_text(expected_answer)
    normalized_hypothesis = _normalize_text(hypothesis)
    if question_type == "single-session-preference":
        return primary_bucket, "preference answer drift"
    if _is_aggregation_question(question):
        return primary_bucket, "aggregation/computation error"
    if question_type == "knowledge-update":
        return primary_bucket, "stale-vs-updated fact selection"
    if normalized_gold and normalized_gold != normalized_hypothesis and normalized_gold in normalized_hypothesis:
        return primary_bucket, "contains gold but extra info / judge strictness"
    if normalized_hypothesis and normalized_gold != normalized_hypothesis and normalized_hypothesis in normalized_gold:
        return primary_bucket, "partial answer / underspecified"
    if _is_temporal_question(question) or question_type == "temporal-reasoning":
        return primary_bucket, "temporal reasoning error"
    return primary_bucket, "fact selection / synthesis error"


def _gold_turn_in_bundle(
    *,
    gold_turns: Sequence[tuple[str, int, str]],
    retrieved_turn_ids: Sequence[str],
    bundle_window: int,
) -> tuple[bool, list[str]]:
    retrieved_turns_by_session: dict[str, list[int]] = defaultdict(list)
    for turn_id in retrieved_turn_ids:
        session_id, turn_number = _parse_turn_id(turn_id)
        if session_id is None or turn_number is None:
            continue
        retrieved_turns_by_session[session_id].append(turn_number)

    covered_turn_ids: list[str] = []
    for gold_turn_id, gold_turn_number, _ in gold_turns:
        gold_session_id, _ = _parse_turn_id(gold_turn_id)
        if gold_session_id is None:
            continue
        if any(
            abs(gold_turn_number - retrieved_turn_number) <= bundle_window
            for retrieved_turn_number in retrieved_turns_by_session.get(gold_session_id, [])
        ):
            covered_turn_ids.append(gold_turn_id)
    return bool(covered_turn_ids), covered_turn_ids


def _extract_gold_turns(reference: Mapping[str, Any]) -> list[tuple[str, int, str]]:
    gold_turns: list[tuple[str, int, str]] = []
    session_ids = reference.get("haystack_session_ids") or []
    sessions = reference.get("haystack_sessions") or []
    for session_id, session_turns in zip(session_ids, sessions):
        turn_number = 0
        for turn in session_turns or []:
            role = str((turn or {}).get("role") or "")
            if role not in {"user", "assistant"}:
                continue
            if bool((turn or {}).get("has_answer", False)):
                gold_turn_id = f"{session_id}:turn-{turn_number}"
                gold_turns.append((gold_turn_id, turn_number, str((turn or {}).get("content") or "")))
            turn_number += 1
    return gold_turns


def _bundle_neighbor_window(question: str) -> int:
    lowered = str(question or "").lower()
    temporal_markers = (
        " first",
        " before",
        " after",
        " earlier",
        " later",
        " last ",
        " most recent",
        " happened first",
        " occurred first",
    )
    return 6 if any(marker in lowered for marker in temporal_markers) else 5


def _parse_turn_id(turn_id: str) -> tuple[str | None, int | None]:
    match = TURN_ID_RE.search(str(turn_id or ""))
    if not match:
        return None, None
    return match.group(1), int(match.group(2))


def _is_aggregation_question(question: str) -> bool:
    lowered = str(question or "").lower()
    return any(
        marker in lowered
        for marker in (
            "how many",
            "how much total",
            "total",
            "combined",
            "altogether",
            "sum",
            "spent",
            "cost",
            "in total",
            "overall",
        )
    )


def _is_temporal_question(question: str) -> bool:
    lowered = str(question or "").lower()
    return any(
        marker in lowered
        for marker in (
            "before",
            "after",
            "ago",
            "last ",
            "first",
            "most recent",
            "earlier",
            "later",
            "when",
            "how long",
            "how many days",
            "how many weeks",
            "how many months",
        )
    )


def _normalize_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def _counter_rates(counter: Mapping[str, int], total: int) -> dict[str, float]:
    if total <= 0:
        return {key: 0.0 for key in counter}
    return {key: round(value / total, 4) for key, value in counter.items()}


def _to_clean_str_list(values: Iterable[Any]) -> list[str]:
    return [str(value).strip() for value in values if str(value).strip()]


def _serialize_row(row: Mapping[str, Any]) -> dict[str, Any]:
    serialized = dict(row)
    for key in ("gold_session_ids", "retrieved_session_ids", "gold_turn_ids", "covered_gold_turn_ids", "retrieved_turn_ids"):
        serialized[key] = json.dumps(serialized.get(key) or [], ensure_ascii=False)
    return serialized


def _load_json_or_jsonl(path: str | Path) -> list[dict[str, Any]]:
    raw_path = Path(path)
    text = raw_path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    if isinstance(data, list):
        return [dict(item) for item in data]
    raise ValueError(f"Expected a JSON list or JSONL file: {raw_path}")


if __name__ == "__main__":
    raise SystemExit(main())
