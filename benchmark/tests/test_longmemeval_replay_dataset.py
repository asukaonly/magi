"""Tests for LongMemEval replay-only CLI helpers."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from benchmark.common.io import read_jsonl
from benchmark.longmemeval.replay_dataset import replay_longmemeval_rows


@dataclass
class FakeReplayService:
    def __post_init__(self) -> None:
        self.write_calls: list[tuple[str, int]] = []
        self.finalize_calls = 0

    async def write_records(self, *, namespace: str, records):
        self.write_calls.append((namespace, len(records)))
        return [{"namespace": namespace, "count": len(records)}]

    async def finalize_replay(self):
        self.finalize_calls += 1
        return {
            "summaries": {
                "hour": {"summary_id": "sum-hour-1"},
                "day": {"summary_id": "sum-day-1"},
                "week": None,
                "month": None,
            },
            "l2_pipeline_stats": {
                "is_running": True,
                "extract_enqueued": 10,
                "extract_completed": 9,
            },
        }


def _build_sample_row(question_id: str = "q-1") -> dict[str, object]:
    return {
        "question_id": question_id,
        "question_type": "multi-session",
        "question": "What food do I prefer?",
        "answer": "Sushi",
        "question_date": "2024-01-10",
        "answer_session_ids": ["sess-2"],
        "haystack_session_ids": ["sess-1", "sess-2"],
        "haystack_dates": ["2024-01-01", "2024-01-05"],
        "haystack_sessions": [
            [{"role": "user", "content": "I like pasta."}],
            [{"role": "user", "content": "Actually sushi is my favorite.", "has_answer": True}],
        ],
    }


def test_replay_script_writes_records_and_manifest(tmp_path) -> None:
    service = FakeReplayService()

    artifacts = asyncio.run(
        replay_longmemeval_rows(
            rows=[_build_sample_row()],
            eval_service=service,
            run_id="run-1",
            output_root=tmp_path,
        )
    )

    assert service.write_calls == [("benchmark/longmemeval/run-1/q-1", 2)]
    assert service.finalize_calls == 1
    manifest_rows = read_jsonl(artifacts.manifest_path)
    assert manifest_rows == [
        {
            "question_id": "q-1",
            "question_type": "multi-session",
            "namespace": "benchmark/longmemeval/run-1/q-1",
            "replay_record_count": 2,
            "answer_session_ids": ["sess-2"],
            "metadata": {
                "question_date": "2024-01-10",
                "question_type": "multi-session",
                "is_abstention": False,
            },
        }
    ]
    post_replay = json.loads(artifacts.post_replay_path.read_text(encoding="utf-8"))
    assert post_replay["summaries"]["hour"]["summary_id"] == "sum-hour-1"
    assert post_replay["l2_pipeline_stats"]["extract_completed"] == 9
