"""Tests for LongMemEval replay-only CLI helpers."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass

from benchmark.common.io import read_jsonl
from benchmark.longmemeval.replay_dataset import parse_args, replay_longmemeval_rows


@dataclass
class FakeReplayService:
    def __post_init__(self) -> None:
        self.write_calls: list[tuple[str, int]] = []
        self.calls: list[tuple[str, object]] = []
        self.finalize_calls = 0
        self.l2_stats_calls = 0
        self.background_pending_calls = 0

    async def write_records(self, *, namespace: str, records):
        self.write_calls.append((namespace, len(records)))
        self.calls.append(("write_records", len(records)))
        return [{"namespace": namespace, "count": len(records)}]

    async def finalize_replay(
        self,
        *,
        generate_summaries: bool = True,
        flush_l2_projection_jobs: bool = True,
        drain_l2_edge_embeddings: bool = True,
    ):
        self.finalize_calls += 1
        self.calls.append(
            (
                "finalize_replay",
                {
                    "generate_summaries": generate_summaries,
                    "flush_l2_projection_jobs": flush_l2_projection_jobs,
                    "drain_l2_edge_embeddings": drain_l2_edge_embeddings,
                },
            )
        )
        return {
            "summaries": {
                "hour": {"summary_id": "sum-hour-1"},
                "day": {"summary_id": "sum-day-1"},
                "week": None,
                "month": None,
            }
            if generate_summaries
            else {},
            "l2_edge_embedding_count": 4 if drain_l2_edge_embeddings else 0,
            "l2_pipeline_stats": {
                "is_running": True,
                "extract_enqueued": 10,
                "extract_completed": 1,
                "extract_failed": 0,
                "extract_skipped": 0,
                "reconcile_enqueued": 0,
                "reconcile_completed": 0,
                "reconcile_failed": 0,
                "snapshot_enqueued": 0,
                "snapshot_completed": 0,
                "snapshot_failed": 0,
            },
        }

    async def get_l2_pipeline_stats(self):
        self.l2_stats_calls += 1
        self.calls.append(("get_l2_pipeline_stats", self.l2_stats_calls))
        if self.l2_stats_calls == 1:
            return {
                "is_running": True,
                "extract_enqueued": 10,
                "extract_completed": 1,
                "extract_failed": 0,
                "extract_skipped": 0,
                "reconcile_enqueued": 2,
                "reconcile_completed": 1,
                "reconcile_failed": 0,
                "snapshot_enqueued": 1,
                "snapshot_completed": 0,
                "snapshot_failed": 0,
                "projection_backlog": {
                    "pending": 0,
                    "claimed": 0,
                    "completed": 0,
                    "failed": 0,
                },
            }
        if self.l2_stats_calls == 2:
            return {
                "is_running": True,
                "extract_enqueued": 10,
                "extract_completed": 10,
                "extract_failed": 0,
                "extract_skipped": 0,
                "reconcile_enqueued": 2,
                "reconcile_completed": 2,
                "reconcile_failed": 0,
                "snapshot_enqueued": 1,
                "snapshot_completed": 1,
                "snapshot_failed": 0,
                "projection_backlog": {
                    "pending": 3,
                    "claimed": 1,
                    "completed": 0,
                    "failed": 0,
                },
            }
        return {
            "is_running": True,
            "extract_enqueued": 10,
            "extract_completed": 10,
            "extract_failed": 0,
            "extract_skipped": 0,
            "reconcile_enqueued": 2,
            "reconcile_completed": 2,
            "reconcile_failed": 0,
            "snapshot_enqueued": 1,
            "snapshot_completed": 1,
            "snapshot_failed": 0,
            "projection_backlog": {
                "pending": 0,
                "claimed": 0,
                "completed": 4,
                "failed": 0,
            },
        }

    async def get_background_pending(self):
        self.background_pending_calls += 1
        self.calls.append(("get_background_pending", self.background_pending_calls))
        if self.background_pending_calls == 1:
            return {
                "l2": {
                    "extract_pending": 0,
                    "reconcile_pending": 0,
                    "snapshot_pending": 0,
                },
                "l1_embeddings": {"pending": 4, "worker_running": True},
                "l2_edge_embeddings": {"pending": 0},
                "l3_embeddings": {"pending": 1, "worker_running": True},
                "l4_embeddings": {"pending": 0, "worker_running": False},
                "all_idle": False,
            }
        return {
            "l2": {
                "extract_pending": 0,
                "reconcile_pending": 0,
                "snapshot_pending": 0,
                },
                "l1_embeddings": {"pending": 0, "worker_running": True},
                "l2_edge_embeddings": {"pending": 0},
                "l3_embeddings": {"pending": 0, "worker_running": True},
                "l4_embeddings": {"pending": 0, "worker_running": False},
                "all_idle": True,
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
    progress_events: list[dict[str, object]] = []

    artifacts = asyncio.run(
        replay_longmemeval_rows(
            rows=[_build_sample_row()],
            eval_service=service,
            run_id="run-1",
            output_root=tmp_path,
            progress_reporter=lambda progress: progress_events.append(asdict(progress)),
            poll_interval_seconds=0.0,
        )
    )

    assert service.write_calls == [("benchmark/longmemeval/run-1/q-1", 2)]
    assert service.finalize_calls == 2
    assert progress_events == [
        {
            "question_index": 1,
            "total_questions": 1,
            "question_id": "q-1",
            "namespace": "benchmark/longmemeval/run-1/q-1",
            "question_record_count": 2,
            "total_record_count": 2,
        }
    ]
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
    assert post_replay["l2_pipeline_stats"]["extract_completed"] == 10
    assert post_replay["l2_pipeline_stats"]["projection_backlog"]["pending"] == 0
    assert post_replay["l2_pipeline_stats"]["projection_backlog"]["claimed"] == 0
    assert post_replay["post_l2_finalize"]["summaries"]["hour"]["summary_id"] == "sum-hour-1"
    assert post_replay["post_l2_finalize"]["l2_edge_embedding_count"] == 4
    assert post_replay["post_l2_pipeline_stats"]["extract_completed"] == 10
    assert post_replay["background_pending"]["all_idle"] is True
    assert service.l2_stats_calls == 4
    assert service.background_pending_calls == 2
    assert service.calls == [
        ("write_records", 2),
        (
            "finalize_replay",
            {
                "generate_summaries": False,
                "flush_l2_projection_jobs": True,
                "drain_l2_edge_embeddings": False,
            },
        ),
        ("get_l2_pipeline_stats", 1),
        ("get_l2_pipeline_stats", 2),
        ("get_l2_pipeline_stats", 3),
        (
            "finalize_replay",
            {
                "generate_summaries": True,
                "flush_l2_projection_jobs": False,
                "drain_l2_edge_embeddings": True,
            },
        ),
        ("get_l2_pipeline_stats", 4),
        ("get_background_pending", 1),
        ("get_background_pending", 2),
    ]


def test_parse_args_accepts_request_timeout_and_poll_interval() -> None:
    args = parse_args(
        [
            "--dataset",
            "/tmp/longmemeval.json",
            "--request-timeout",
            "42.5",
            "--poll-interval-seconds",
            "1.5",
        ]
    )

    assert args.request_timeout == 42.5
    assert args.poll_interval_seconds == 1.5
