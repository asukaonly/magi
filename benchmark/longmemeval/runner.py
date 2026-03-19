"""Replay LongMemEval rows through Magi memory eval support."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = REPO_ROOT / "backend" / "src"
for candidate in (REPO_ROOT, BACKEND_SRC):
    candidate_text = str(candidate)
    if candidate_text not in sys.path:
        sys.path.insert(0, candidate_text)

from magi.memory import UnifiedMemoryStore
from magi.memory.eval_support.namespace import EvalNamespaceManager, build_eval_namespace
from magi.memory.eval_support.reader import EvalMemoryReader
from magi.memory.eval_support.service import EvalMemoryService
from magi.memory.eval_support.writer import EvalMemoryWriter
from magi.memory.hybrid_retrieval import HybridRetrievalService

from benchmark.common.io import write_jsonl
from benchmark.common.paths import build_run_output_dir
from benchmark.longmemeval.adapter import adapt_longmemeval_entry


class SupportsLongMemEvalService(Protocol):
    """Small protocol for the memory-only eval harness used by the runner."""

    async def write_records(self, *, namespace: str, records: list[Any]) -> Any:
        """Replay normalized records into memory."""

    async def query_memory(self, query: Any) -> Any:
        """Execute a memory-only retrieval query."""


@dataclass(slots=True)
class LongMemEvalRunArtifacts:
    """Output files produced by a single runner invocation."""

    output_dir: Path
    predictions_path: Path
    predictions_with_trace_path: Path


@dataclass(slots=True)
class LongMemEvalRuntime:
    """Async lifecycle wrapper for a default local memory harness."""

    service: EvalMemoryService
    memory: UnifiedMemoryStore

    async def shutdown(self) -> None:
        await self.memory.shutdown()


def load_longmemeval_rows(dataset_path: str | Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    rows = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("LongMemEval dataset must be a JSON list.")
    if limit is not None:
        return [dict(row) for row in rows[:limit]]
    return [dict(row) for row in rows]


def synthesize_hypothesis_from_hits(*, hits: Sequence[Any], fallback: str = "unknown", max_hits: int = 3) -> str:
    snippets: list[str] = []
    for hit in hits[:max_hits]:
        content = str(getattr(hit, "content", "") or "").strip()
        if content:
            snippets.append(content)
    return "\n".join(snippets) if snippets else fallback


async def run_longmemeval_rows(
    *,
    rows: Sequence[dict[str, Any]],
    eval_service: SupportsLongMemEvalService,
    run_id: str,
    output_root: str | Path,
    benchmark_name: str = "longmemeval",
) -> LongMemEvalRunArtifacts:
    output_dir = build_run_output_dir(
        root_dir=output_root,
        benchmark_name=benchmark_name,
        run_id=run_id,
    )

    predictions: list[dict[str, str]] = []
    traced_predictions: list[dict[str, Any]] = []

    for row in rows:
        question_id = str(row.get("question_id") or "")
        namespace = build_eval_namespace(
            benchmark_name=benchmark_name,
            run_id=run_id,
            question_id=question_id,
        )
        adapted = adapt_longmemeval_entry(row, namespace=namespace)
        await eval_service.write_records(
            namespace=namespace,
            records=adapted.replay_records,
        )
        query_result = await eval_service.query_memory(adapted.query)
        hypothesis = synthesize_hypothesis_from_hits(hits=query_result.hits)

        predictions.append(
            {
                "question_id": adapted.question_id,
                "hypothesis": hypothesis,
            }
        )
        traced_predictions.append(
            {
                "question_id": adapted.question_id,
                "question_type": adapted.question_type,
                "expected_answer": adapted.expected_answer,
                "answer_session_ids": adapted.answer_session_ids,
                "namespace": namespace,
                "hypothesis": hypothesis,
                "retrieved_session_ids": query_result.retrieved_session_ids,
                "retrieved_turn_ids": query_result.retrieved_turn_ids,
                "retrieved_event_ids": query_result.retrieved_event_ids,
                "trace": query_result.trace,
                "metadata": adapted.metadata,
            }
        )

    predictions_path = write_jsonl(output_dir / "predictions.jsonl", predictions)
    predictions_with_trace_path = write_jsonl(
        output_dir / "predictions_with_trace.jsonl",
        traced_predictions,
    )
    return LongMemEvalRunArtifacts(
        output_dir=output_dir,
        predictions_path=predictions_path,
        predictions_with_trace_path=predictions_with_trace_path,
    )


async def create_default_runtime(*, state_dir: str | Path) -> LongMemEvalRuntime:
    state_path = Path(state_dir)
    state_path.mkdir(parents=True, exist_ok=True)

    memory = UnifiedMemoryStore(
        db_path=str(state_path / "l1_memory.db"),
        persist_dir=str(state_path / "memories"),
        memory_db_path=str(state_path / "memory.db"),
        enable_l0=False,
        enable_l1=True,
        enable_l2=False,
        enable_l3=False,
        enable_l4=False,
        enable_l1_vectors=True,
    )
    await memory.initialize()
    service = EvalMemoryService(
        namespace_manager=EvalNamespaceManager(),
        writer=EvalMemoryWriter(memory),
        reader=EvalMemoryReader(HybridRetrievalService(memory)),
    )
    return LongMemEvalRuntime(service=service, memory=memory)


async def _run_cli(args: argparse.Namespace) -> LongMemEvalRunArtifacts:
    rows = load_longmemeval_rows(args.dataset, limit=args.limit)
    output_dir = build_run_output_dir(
        root_dir=args.output_root,
        benchmark_name="longmemeval",
        run_id=args.run_id,
    )
    runtime = await create_default_runtime(state_dir=output_dir / "state")
    try:
        return await run_longmemeval_rows(
            rows=rows,
            eval_service=runtime.service,
            run_id=args.run_id,
            output_root=args.output_root,
        )
    finally:
        await runtime.shutdown()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run LongMemEval against Magi memory eval support.")
    parser.add_argument("--dataset", required=True, help="Path to a LongMemEval JSON dataset file.")
    parser.add_argument("--output-root", default="benchmark/outputs", help="Directory for benchmark outputs.")
    parser.add_argument("--run-id", default="smoke", help="Logical run identifier.")
    parser.add_argument("--limit", type=int, default=None, help="Optional sample limit for quick runs.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    artifacts = asyncio.run(_run_cli(args))
    print(f"Wrote {artifacts.predictions_path}")
    print(f"Wrote {artifacts.predictions_with_trace_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
