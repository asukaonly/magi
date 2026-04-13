"""Batch-query multiple LongMemEval questions and capture results + backend logs."""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = REPO_ROOT / "backend" / "src"
for candidate in (REPO_ROOT, BACKEND_SRC):
    candidate_text = str(candidate)
    if candidate_text not in sys.path:
        sys.path.insert(0, candidate_text)

from benchmark.common.paths import resolve_backend_url
from benchmark.longmemeval.backend_client import BackendEvalService
from benchmark.longmemeval.query_one import build_single_query_payload, select_question_row
from benchmark.longmemeval.runner import load_longmemeval_rows
from magi.memory.eval_support.namespace import build_eval_namespace

DEFAULT_LOG_PATH = Path.home() / ".magi" / "logs" / "magi.log"


def _tail_log_since(log_path: Path, start_pos: int, namespace: str) -> list[str]:
    """Read log lines appended since *start_pos* and return those matching *namespace*."""
    if not log_path.exists():
        return []
    with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
        fh.seek(start_pos)
        lines = fh.readlines()
    return [line.rstrip("\n") for line in lines if namespace in line]


def _log_file_end(log_path: Path) -> int:
    """Return the current byte offset at end of the log file."""
    if not log_path.exists():
        return 0
    return log_path.stat().st_size


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch-query LongMemEval questions and capture results + backend logs."
    )
    parser.add_argument(
        "--dataset",
        required=True,
        help="Path to a LongMemEval JSON dataset file.",
    )
    parser.add_argument(
        "--run-id",
        required=True,
        help="Existing run identifier used during replay.",
    )
    parser.add_argument(
        "question_ids",
        nargs="+",
        help="One or more LongMemEval question ids to query.",
    )
    parser.add_argument(
        "--backend-url",
        default=None,
        help="Magi backend base URL (auto-detected if omitted).",
    )
    parser.add_argument(
        "--mode",
        default="auto",
        help="Memory retrieval mode hint.",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=120.0,
        help="HTTP timeout in seconds per query.",
    )
    parser.add_argument(
        "--answer-with-llm",
        action="store_true",
        help="Use backend LLM to synthesize a final answer.",
    )
    parser.add_argument(
        "--show-prompt",
        action="store_true",
        help="Include the synthesized LLM prompt in debug output.",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output file path. Defaults to outputs/longmemeval/batch-<timestamp>.txt",
    )
    parser.add_argument(
        "--log-path",
        default=None,
        help=f"Magi backend log file path (default: {DEFAULT_LOG_PATH}).",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    log_path = Path(args.log_path) if args.log_path else DEFAULT_LOG_PATH
    backend_url = args.backend_url or resolve_backend_url()
    rows = load_longmemeval_rows(args.dataset)
    eval_service = BackendEvalService(backend_url, timeout_seconds=args.request_timeout)

    # Resolve output path
    if args.output:
        output_path = Path(args.output)
    else:
        ts = datetime.now(timezone.utc).strftime("%m%d-%H%M%S")
        output_path = (
            REPO_ROOT / "outputs" / "longmemeval" / f"batch-{ts}.txt"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    question_ids: list[str] = args.question_ids
    total = len(question_ids)
    passed = 0
    failed = 0

    with open(output_path, "w", encoding="utf-8") as out:
        header = (
            f"Batch query: {total} questions  run_id={args.run_id}  "
            f"mode={args.mode}  answer_with_llm={args.answer_with_llm}\n"
            f"Backend: {backend_url}\n"
            f"Log file: {log_path}\n"
            f"Started: {datetime.now(timezone.utc).isoformat()}\n"
        )
        out.write(header)
        out.write("=" * 80 + "\n\n")
        print(header, flush=True)

        for idx, qid in enumerate(question_ids, 1):
            banner = f"[{idx}/{total}] question_id={qid}"
            print(banner, flush=True)
            out.write(f"{'=' * 80}\n")
            out.write(f"{banner}\n")
            out.write(f"{'=' * 80}\n")

            try:
                row = select_question_row(rows, qid)
            except ValueError as exc:
                msg = f"  SKIP: {exc}\n"
                print(msg, end="", flush=True)
                out.write(msg + "\n")
                failed += 1
                continue

            namespace = build_eval_namespace(
                benchmark_name="longmemeval",
                run_id=args.run_id,
                question_id=qid,
            )

            # Record log position before query
            log_start = _log_file_end(log_path)

            # Execute query
            t0 = time.monotonic()
            try:
                coro = build_single_query_payload(
                    row=row,
                    eval_service=eval_service,
                    run_id=args.run_id,
                    mode=args.mode,
                    answer_with_llm=args.answer_with_llm,
                    show_prompt=args.show_prompt,
                )
                payload = asyncio.run(coro) if inspect.iscoroutine(coro) else coro
                elapsed = time.monotonic() - t0
                passed += 1
            except Exception as exc:
                elapsed = time.monotonic() - t0
                out.write(f"  ERROR ({elapsed:.1f}s): {exc}\n\n")
                print(f"  ERROR ({elapsed:.1f}s): {exc}", flush=True)
                failed += 1
                # Still capture logs even on error
                log_lines = _tail_log_since(log_path, log_start, namespace)
                if log_lines:
                    out.write(f"--- Backend logs ({len(log_lines)} lines) ---\n")
                    out.write("\n".join(log_lines) + "\n")
                out.write("\n")
                continue

            # Write result summary
            answer = payload.get("answer") or payload.get("hypothesis") or ""
            expected = payload.get("expected_answer") or ""
            hit_count = len(payload.get("hits") or [])
            bundle_count = len(payload.get("evidence_bundles") or [])
            retrieved_sessions = payload.get("retrieved_session_ids") or []
            answer_sessions = payload.get("answer_session_ids") or []

            summary = (
                f"  type:       {payload.get('question_type', '?')}\n"
                f"  question:   {payload.get('question', '?')}\n"
                f"  expected:   {expected}\n"
                f"  answer:     {answer}\n"
                f"  hits:       {hit_count}   bundles: {bundle_count}\n"
                f"  sessions:   retrieved={sorted(retrieved_sessions)}  answer={sorted(answer_sessions)}\n"
                f"  elapsed:    {elapsed:.1f}s\n"
            )
            out.write(summary)
            print(f"  hits={hit_count}  bundles={bundle_count}  elapsed={elapsed:.1f}s", flush=True)

            # Write full payload
            out.write("\n--- Full payload ---\n")
            out.write(json.dumps(payload, ensure_ascii=False, indent=2))
            out.write("\n")

            # Capture and write backend logs
            log_lines = _tail_log_since(log_path, log_start, namespace)
            out.write(f"\n--- Backend logs ({len(log_lines)} lines) ---\n")
            if log_lines:
                out.write("\n".join(log_lines) + "\n")
            else:
                out.write("(no matching log lines)\n")
            out.write("\n")

        # Footer
        footer = (
            f"\n{'=' * 80}\n"
            f"Done: {passed} passed, {failed} failed, {total} total\n"
            f"Finished: {datetime.now(timezone.utc).isoformat()}\n"
        )
        out.write(footer)
        print(footer, flush=True)

    print(f"Output written to: {output_path}", flush=True)
    return 1 if failed == total else 0


if __name__ == "__main__":
    raise SystemExit(main())
