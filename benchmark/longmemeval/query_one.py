"""Debug a single LongMemEval question against previously replayed memory."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import inspect
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Protocol, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = REPO_ROOT / "backend" / "src"
for candidate in (REPO_ROOT, BACKEND_SRC):
    candidate_text = str(candidate)
    if candidate_text not in sys.path:
        sys.path.insert(0, candidate_text)

from benchmark.common.paths import resolve_backend_url
from benchmark.longmemeval.adapter import adapt_longmemeval_entry
from benchmark.longmemeval.backend_client import BackendEvalService
from benchmark.longmemeval.runner import load_longmemeval_rows, synthesize_hypothesis_from_hits
from magi.memory.eval_support.namespace import build_eval_namespace


class SupportsQueryService(Protocol):
    """Small protocol for single-question memory retrieval."""

    async def query_memory(self, query: Any) -> Any:
        """Execute a memory query."""


def select_question_row(rows: Sequence[dict[str, Any]], question_id: str) -> dict[str, Any]:
    """Return the dataset row matching a LongMemEval question id."""
    for row in rows:
        if str(row.get("question_id") or "") == question_id:
            return dict(row)
    raise ValueError(f"Question id not found in dataset: {question_id}")


async def build_single_query_payload(
    *,
    row: dict[str, Any],
    eval_service: SupportsQueryService,
    run_id: str,
    mode: str = "auto",
    answer_with_llm: bool = False,
    show_prompt: bool = False,
    benchmark_name: str = "longmemeval",
) -> dict[str, Any]:
    """Query one replayed LongMemEval item and return a JSON-friendly debug payload."""
    question_id = str(row.get("question_id") or "")
    namespace = build_eval_namespace(
        benchmark_name=benchmark_name,
        run_id=run_id,
        question_id=question_id,
    )
    adapted = adapt_longmemeval_entry(row, namespace=namespace)
    query_result = await eval_service.query_memory(
        replace(adapted.query, mode=mode, answer_with_llm=answer_with_llm, show_prompt=show_prompt)
    )
    hypothesis = query_result.answer or synthesize_hypothesis_from_hits(hits=query_result.hits)
    return {
        "question_id": adapted.question_id,
        "question_type": adapted.question_type,
        "question": adapted.query.query,
        "expected_answer": adapted.expected_answer,
        "answer_session_ids": adapted.answer_session_ids,
        "namespace": namespace,
        "answer_with_llm": answer_with_llm,
        "hypothesis": hypothesis,
        "answer": query_result.answer,
        "hits": [asdict(hit) for hit in query_result.hits],
        "evidence_bundles": query_result.evidence_bundles,
        "timeline_summary": query_result.timeline_summary,
        "retrieved_session_ids": query_result.retrieved_session_ids,
        "retrieved_turn_ids": query_result.retrieved_turn_ids,
        "retrieved_event_ids": query_result.retrieved_event_ids,
        "trace": query_result.trace,
        "answer_trace": query_result.answer_trace,
        "metadata": adapted.metadata,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query a single LongMemEval question against replayed Magi memory.")
    parser.add_argument("--dataset", required=True, help="Path to a LongMemEval JSON dataset file.")
    parser.add_argument("--run-id", required=True, help="Existing run identifier used during replay.")
    parser.add_argument("--question-id", required=True, help="LongMemEval question id to debug.")
    parser.add_argument("--backend-url", default=None, help="Magi backend base URL (auto-detected from ~/.magi/config/agent.yaml if omitted).")
    parser.add_argument(
        "--mode",
        default="auto",
        help="Memory retrieval mode hint (auto|detail|summary|experience|graph|strategy|l1_only).",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=120.0,
        help="HTTP timeout in seconds for the backend query request.",
    )
    parser.add_argument(
        "--answer-with-llm",
        action="store_true",
        help="Use the backend LLM to synthesize a final answer from retrieved hits.",
    )
    parser.add_argument(
        "--show-prompt",
        action="store_true",
        help="Include the synthesized LLM prompt in the debug output.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    rows = load_longmemeval_rows(args.dataset)
    row = select_question_row(rows, args.question_id)
    question_id = str(row.get("question_id") or "")
    namespace = build_eval_namespace(
        benchmark_name="longmemeval",
        run_id=args.run_id,
        question_id=question_id,
    )
    print(
        f"Querying LongMemEval question_id={question_id} "
        f"namespace={namespace} "
        f"mode={args.mode} "
        f"answer_with_llm={args.answer_with_llm} "
        f"show_prompt={args.show_prompt}",
        flush=True,
    )
    build_result = build_single_query_payload(
        row=row,
        eval_service=BackendEvalService(args.backend_url or resolve_backend_url(), timeout_seconds=args.request_timeout),
        run_id=args.run_id,
        mode=args.mode,
        answer_with_llm=args.answer_with_llm,
        show_prompt=args.show_prompt,
    )
    payload = asyncio.run(build_result) if inspect.iscoroutine(build_result) else build_result
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
