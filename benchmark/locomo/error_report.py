"""Analyze LoCoMo non-perfect answers into retrieval and answer buckets."""

from __future__ import annotations

import argparse
import csv
import json
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
from benchmark.locomo.report import score_locomo_qa


CSV_COLUMNS = [
    "question_id",
    "sample_id",
    "category",
    "category_label",
    "score",
    "primary_bucket",
    "secondary_bucket",
    "question",
    "expected_answer",
    "hypothesis",
    "evidence_turn_hit",
    "answer_session_hit",
    "top1_session_hit",
    "evidence",
    "answer_session_ids",
    "retrieved_session_ids",
    "retrieved_turn_ids",
]


@dataclass(slots=True)
class LoCoMoErrorAnalysisReport:
    """Structured non-perfect answer report for a LoCoMo run."""

    rows: list[dict[str, Any]]
    summary: dict[str, Any]


@dataclass(slots=True)
class LoCoMoErrorReportArtifacts:
    """Files written by the LoCoMo error analysis exporter."""

    csv_path: Path
    jsonl_path: Path
    summary_path: Path


def analyze_prediction_errors(
    predictions: Sequence[Mapping[str, Any]],
    *,
    top_k: int = 5,
) -> LoCoMoErrorAnalysisReport:
    """Bucket non-perfect answers by likely retrieval or answer failure."""
    rows: list[dict[str, Any]] = []
    primary_buckets: Counter[str] = Counter()
    secondary_buckets: Counter[str] = Counter()
    by_category: dict[str, Counter[str]] = defaultdict(Counter)
    meta: Counter[str] = Counter()

    for prediction in predictions:
        category = _to_int(prediction.get("category"))
        score = score_locomo_qa(
            category=category,
            prediction=str(prediction.get("hypothesis") or ""),
            answer=str(prediction.get("expected_answer") or ""),
        )
        if score >= 1.0:
            continue

        evidence_turn_ids = _to_clean_str_list(prediction.get("evidence") or [])
        answer_session_ids = _to_clean_str_list(prediction.get("answer_session_ids") or [])
        if not answer_session_ids:
            answer_session_ids = _answer_session_ids_from_evidence(evidence_turn_ids)
        retrieved_session_ids = _to_clean_str_list(prediction.get("retrieved_session_ids") or [])
        retrieved_turn_ids = _to_clean_str_list(prediction.get("retrieved_turn_ids") or [])

        evidence_turn_hit = bool(set(evidence_turn_ids) & set(retrieved_turn_ids))
        answer_session_hit = bool(set(answer_session_ids) & set(retrieved_session_ids))
        top1_session_hit = bool(retrieved_session_ids[:1]) and bool(
            set(answer_session_ids) & set(retrieved_session_ids[:1])
        )
        topk_session_hit = bool(set(answer_session_ids) & set(retrieved_session_ids[:top_k]))

        primary_bucket, secondary_bucket = _classify_error(
            category=category,
            score=score,
            evidence_turn_hit=evidence_turn_hit,
            answer_session_hit=answer_session_hit,
            top1_session_hit=top1_session_hit,
            topk_session_hit=topk_session_hit,
        )
        row = {
            "question_id": str(prediction.get("question_id") or ""),
            "sample_id": str(prediction.get("sample_id") or ""),
            "category": category,
            "category_label": str(prediction.get("category_label") or ""),
            "score": round(score, 4),
            "primary_bucket": primary_bucket,
            "secondary_bucket": secondary_bucket,
            "question": str(prediction.get("question") or ""),
            "expected_answer": str(prediction.get("expected_answer") or ""),
            "hypothesis": str(prediction.get("hypothesis") or ""),
            "evidence_turn_hit": evidence_turn_hit,
            "answer_session_hit": answer_session_hit,
            "top1_session_hit": top1_session_hit,
            "topk_session_hit": topk_session_hit,
            "evidence": evidence_turn_ids,
            "answer_session_ids": answer_session_ids,
            "retrieved_session_ids": retrieved_session_ids,
            "retrieved_turn_ids": retrieved_turn_ids,
        }
        rows.append(row)
        primary_buckets[primary_bucket] += 1
        secondary_buckets[secondary_bucket] += 1
        by_category[str(category)][primary_bucket] += 1
        if evidence_turn_hit:
            meta["evidence_turn_hit"] += 1
        if answer_session_hit:
            meta["answer_session_hit"] += 1
        if top1_session_hit:
            meta["top1_session_hit"] += 1
        if topk_session_hit:
            meta[f"top{top_k}_session_hit"] += 1

    summary = _build_summary(
        rows=rows,
        total_predictions=len(predictions),
        primary_buckets=primary_buckets,
        secondary_buckets=secondary_buckets,
        by_category=by_category,
        meta=meta,
        top_k=top_k,
    )
    return LoCoMoErrorAnalysisReport(rows=rows, summary=summary)


def export_error_report(output_dir: str | Path, report: LoCoMoErrorAnalysisReport) -> LoCoMoErrorReportArtifacts:
    """Write LoCoMo non-perfect answer tables as CSV, JSONL, and summary JSON."""
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
    return LoCoMoErrorReportArtifacts(
        csv_path=csv_path,
        jsonl_path=jsonl_path,
        summary_path=summary_path,
    )


def run_error_analysis(
    *,
    predictions_with_trace_path: str | Path,
    output_dir: str | Path,
    top_k: int = 5,
) -> LoCoMoErrorReportArtifacts:
    """Load LoCoMo predictions, analyze non-perfect answers, and export a report."""
    predictions = read_jsonl(predictions_with_trace_path)
    report = analyze_prediction_errors(predictions, top_k=top_k)
    return export_error_report(output_dir, report)


def build_default_paths(*, output_root: str | Path, run_id: str) -> tuple[Path, Path]:
    """Resolve default file locations for an existing LoCoMo run."""
    run_dir = build_run_output_dir(
        root_dir=output_root,
        benchmark_name="locomo",
        run_id=run_id,
    )
    return run_dir, run_dir / "predictions_with_trace.jsonl"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a bucketed LoCoMo wrong-answer report.")
    parser.add_argument("--output-root", default="benchmark/outputs", help="Directory containing benchmark outputs.")
    parser.add_argument("--run-id", required=True, help="Benchmark run identifier.")
    parser.add_argument(
        "--predictions-with-trace",
        help="Optional explicit path to predictions_with_trace.jsonl. Overrides --output-root/--run-id.",
    )
    parser.add_argument("--top-k", type=int, default=5, help="Top-k session cutoff used in the summary.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    run_dir, default_predictions_path = build_default_paths(
        output_root=args.output_root,
        run_id=args.run_id,
    )
    predictions_with_trace_path = Path(args.predictions_with_trace or default_predictions_path)
    artifacts = run_error_analysis(
        predictions_with_trace_path=predictions_with_trace_path,
        output_dir=run_dir,
        top_k=args.top_k,
    )
    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    print(f"Wrote {artifacts.csv_path}")
    print(f"Wrote {artifacts.jsonl_path}")
    print(f"Wrote {artifacts.summary_path}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _classify_error(
    *,
    category: int,
    score: float,
    evidence_turn_hit: bool,
    answer_session_hit: bool,
    top1_session_hit: bool,
    topk_session_hit: bool,
) -> tuple[str, str]:
    if int(category) == 5:
        return "D. adversarial miss", "should abstain with official phrase"
    if not answer_session_hit:
        return "A. answer session miss", "no answer session retrieved"
    if not evidence_turn_hit:
        if top1_session_hit:
            return "B. same session, evidence turn miss", "right session ranked first"
        if topk_session_hit:
            return "B. same session, evidence turn miss", "right session outside top1"
        return "B. same session, evidence turn miss", "right session retrieved late"
    if 0.0 < score < 1.0:
        return "C. partial answer / strict scoring", "semantic partial or formatting gap"
    return "E. evidence present, answer miss", "answer synthesis mismatch"


def _build_summary(
    *,
    rows: Sequence[Mapping[str, Any]],
    total_predictions: int,
    primary_buckets: Counter[str],
    secondary_buckets: Counter[str],
    by_category: Mapping[str, Counter[str]],
    meta: Counter[str],
    top_k: int,
) -> dict[str, Any]:
    non_perfect_count = len(rows)
    return {
        "total_questions": total_predictions,
        "non_perfect_question_count": non_perfect_count,
        "non_perfect_rate": _rate(non_perfect_count, total_predictions),
        "top_k": top_k,
        "primary_buckets": dict(primary_buckets),
        "primary_bucket_rates": _counter_rates(primary_buckets, non_perfect_count),
        "secondary_buckets": dict(secondary_buckets),
        "secondary_bucket_rates": _counter_rates(secondary_buckets, non_perfect_count),
        "meta": dict(meta),
        "meta_rates": _counter_rates(meta, non_perfect_count),
        "by_category": {
            category: {
                "non_perfect_count": sum(counter.values()),
                "primary_buckets": dict(counter),
            }
            for category, counter in by_category.items()
        },
    }


def _counter_rates(counter: Mapping[str, int], total: int) -> dict[str, float]:
    if total <= 0:
        return {key: 0.0 for key in counter}
    return {key: _rate(value, total) for key, value in counter.items()}


def _rate(value: int, total: int) -> float:
    return round(value / total, 4) if total > 0 else 0.0


def _answer_session_ids_from_evidence(evidence: Sequence[str]) -> list[str]:
    session_ids: list[str] = []
    for item in evidence:
        text = str(item or "").strip()
        if not text.startswith("D"):
            continue
        session_text = text[1:].split(":", maxsplit=1)[0]
        try:
            session_id = f"session_{int(session_text)}"
        except ValueError:
            continue
        if session_id not in session_ids:
            session_ids.append(session_id)
    return session_ids


def _to_clean_str_list(values: Iterable[Any]) -> list[str]:
    if isinstance(values, str):
        parsed = _try_parse_json_list(values)
        values = parsed if parsed is not None else [values]
    return [str(value).strip() for value in values if str(value).strip()]


def _try_parse_json_list(value: str) -> list[Any] | None:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, list) else None


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _serialize_row(row: Mapping[str, Any]) -> dict[str, Any]:
    serialized = dict(row)
    for key in ("evidence", "answer_session_ids", "retrieved_session_ids", "retrieved_turn_ids"):
        serialized[key] = json.dumps(serialized.get(key) or [], ensure_ascii=False)
    return serialized


if __name__ == "__main__":
    raise SystemExit(main())
