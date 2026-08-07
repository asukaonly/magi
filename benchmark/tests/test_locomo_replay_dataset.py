"""Tests for LoCoMo replay-only helpers."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass

from benchmark.common.io import read_jsonl
from benchmark.locomo.replay_dataset import parse_args, replay_locomo_samples
from benchmark.longmemeval.replay_dataset import (
    describe_l2_pending,
    is_l2_pipeline_idle,
)


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
        summaries = {"day": {"summary_id": "sum-1"}} if generate_summaries else {}
        return {
            "summaries": summaries,
            "l2_edge_embedding_count": 3 if drain_l2_edge_embeddings else 0,
        }

    async def get_l2_pipeline_stats(self):
        self.l2_stats_calls += 1
        self.calls.append(("get_l2_pipeline_stats", self.l2_stats_calls))
        if self.l2_stats_calls == 1:
            return {
                "extract_enqueued": 1,
                "extract_completed": 1,
                "extract_failed": 0,
                "extract_skipped": 0,
                "reconcile_enqueued": 0,
                "reconcile_completed": 0,
                "reconcile_failed": 0,
                "snapshot_enqueued": 0,
                "snapshot_completed": 0,
                "snapshot_failed": 0,
                "projection_backlog": {
                    "pending": 1,
                    "claimed": 0,
                    "completed": 0,
                    "failed": 0,
                },
            }
        return {
            "extract_enqueued": 1,
            "extract_completed": 1,
            "extract_failed": 0,
            "extract_skipped": 0,
            "reconcile_enqueued": 0,
            "reconcile_completed": 0,
            "reconcile_failed": 0,
            "snapshot_enqueued": 0,
            "snapshot_completed": 0,
            "snapshot_failed": 0,
            "projection_backlog": {
                "pending": 0,
                "claimed": 0,
                "completed": 1,
                "failed": 0,
            },
        }

    async def get_background_pending(self):
        self.background_pending_calls += 1
        self.calls.append(("get_background_pending", self.background_pending_calls))
        return {
            "l2": {"extract_pending": 0, "reconcile_pending": 0, "snapshot_pending": 0},
            "l1_embeddings": {"pending": 0},
            "l2_edge_embeddings": {"pending": 0},
            "l3_embeddings": {"pending": 0},
            "l4_embeddings": {"pending": 0},
            "all_idle": True,
        }


@dataclass
class FakePostFinalizeL2Service:
    def __post_init__(self) -> None:
        self.write_calls = 0
        self.calls: list[tuple[str, object]] = []
        self.finalize_calls = 0
        self.l2_stats_calls = 0
        self.background_pending_calls = 0

    async def write_records(self, *, namespace: str, records):
        self.write_calls += 1
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
        return {"summaries": {}, "l2_edge_embedding_count": 0}

    async def get_l2_pipeline_stats(self):
        self.l2_stats_calls += 1
        self.calls.append(("get_l2_pipeline_stats", self.l2_stats_calls))
        if self.l2_stats_calls == 1:
            return _idle_l2_stats()
        if self.l2_stats_calls == 2:
            stats = _idle_l2_stats()
            stats["extract_active"] = 1
            return stats
        return _idle_l2_stats()

    async def get_background_pending(self):
        self.background_pending_calls += 1
        self.calls.append(("get_background_pending", self.background_pending_calls))
        return {
            "l2": {
                "extract_pending": 0,
                "reconcile_pending": 0,
                "snapshot_pending": 0,
            },
            "l1_embeddings": {"pending": 0},
            "l2_edge_embeddings": {"pending": 0},
            "l3_embeddings": {"pending": 0},
            "l4_embeddings": {"pending": 0},
            "all_idle": True,
        }


def _idle_l2_stats() -> dict[str, object]:
    return {
        "extract_enqueued": 1,
        "extract_completed": 1,
        "extract_failed": 0,
        "extract_skipped": 0,
        "extract_active": 0,
        "reconcile_enqueued": 0,
        "reconcile_completed": 0,
        "reconcile_failed": 0,
        "reconcile_active": 0,
        "snapshot_enqueued": 0,
        "snapshot_completed": 0,
        "snapshot_failed": 0,
        "snapshot_active": 0,
        "projection_backlog": {
            "pending": 0,
            "claimed": 0,
            "completed": 1,
            "failed": 0,
        },
    }


def _build_sample() -> dict[str, object]:
    return {
        "sample_id": "conv-test",
        "conversation": {
            "speaker_a": "Caroline",
            "speaker_b": "Melanie",
            "session_1_date_time": "1:56 pm on 8 May, 2023",
            "session_1": [
                {"speaker": "Caroline", "dia_id": "D1:1", "text": "I joined a support group."},
                {"speaker": "Melanie", "dia_id": "D1:2", "text": "I painted a sunrise."},
            ],
        },
        "qa": [
            {
                "question": "What did Caroline join?",
                "answer": "support group",
                "evidence": ["D1:1"],
                "category": 4,
            }
        ],
    }


def test_replay_script_writes_each_conversation_once(tmp_path) -> None:
    service = FakeReplayService()
    progress_events: list[dict[str, object]] = []

    artifacts = asyncio.run(
        replay_locomo_samples(
            samples=[_build_sample()],
            eval_service=service,
            run_id="run-1",
            output_root=tmp_path,
            progress_reporter=lambda progress: progress_events.append(asdict(progress)),
            poll_interval_seconds=0.0,
        )
    )

    assert service.write_calls == [("benchmark/locomo/run-1/conv-test", 2)]
    assert service.finalize_calls == 2
    assert progress_events == [
        {
            "sample_index": 1,
            "total_samples": 1,
            "sample_id": "conv-test",
            "namespace": "benchmark/locomo/run-1/conv-test",
            "replay_record_count": 2,
            "qa_count": 1,
            "total_record_count": 2,
        }
    ]
    assert read_jsonl(artifacts.manifest_path) == [
        {
            "sample_id": "conv-test",
            "namespace": "benchmark/locomo/run-1/conv-test",
            "replay_record_count": 2,
            "qa_count": 1,
            "speakers": ["Caroline", "Melanie"],
        }
    ]
    post_replay = json.loads(artifacts.post_replay_path.read_text(encoding="utf-8"))
    assert post_replay["l2_pipeline_stats"]["extract_completed"] == 1
    assert post_replay["l2_pipeline_stats"]["projection_backlog"]["pending"] == 0
    assert post_replay["post_l2_finalize"]["summaries"]["day"]["summary_id"] == "sum-1"
    assert post_replay["post_l2_finalize"]["l2_edge_embedding_count"] == 3
    assert post_replay["post_l2_pipeline_stats"]["extract_completed"] == 1
    assert post_replay["background_pending"]["all_idle"] is True
    assert service.l2_stats_calls == 3
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
        (
            "finalize_replay",
            {
                "generate_summaries": True,
                "flush_l2_projection_jobs": False,
                "drain_l2_edge_embeddings": True,
            },
        ),
        ("get_l2_pipeline_stats", 3),
        ("get_background_pending", 1),
    ]


def test_replay_script_waits_for_l2_again_after_finalize(tmp_path) -> None:
    service = FakePostFinalizeL2Service()

    artifacts = asyncio.run(
        replay_locomo_samples(
            samples=[_build_sample()],
            eval_service=service,
            run_id="run-1",
            output_root=tmp_path,
            poll_interval_seconds=0.0,
        )
    )

    post_replay = json.loads(artifacts.post_replay_path.read_text(encoding="utf-8"))

    assert post_replay["post_l2_pipeline_stats"]["extract_active"] == 0
    assert service.l2_stats_calls == 3
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
        (
            "finalize_replay",
            {
                "generate_summaries": True,
                "flush_l2_projection_jobs": False,
                "drain_l2_edge_embeddings": True,
            },
        ),
        ("get_l2_pipeline_stats", 2),
        ("get_l2_pipeline_stats", 3),
        ("get_background_pending", 1),
    ]


def test_l2_idle_helpers_treat_active_workers_as_pending() -> None:
    stats = _idle_l2_stats()
    stats["extract_active"] = 1
    pending = describe_l2_pending(stats)

    assert pending["extract_pending"] == 1
    assert pending["extract_active"] == 1
    assert is_l2_pipeline_idle(stats) is False


def test_replay_script_can_skip_finalize_and_background_wait(tmp_path) -> None:
    service = FakeReplayService()

    artifacts = asyncio.run(
        replay_locomo_samples(
            samples=[_build_sample()],
            eval_service=service,
            run_id="run-1",
            output_root=tmp_path,
            finalize=False,
            wait_for_background=False,
        )
    )

    assert service.finalize_calls == 0
    assert service.l2_stats_calls == 0
    assert service.background_pending_calls == 0
    post_replay = json.loads(artifacts.post_replay_path.read_text(encoding="utf-8"))
    assert post_replay == {
        "finalize": {"status": "skipped"},
        "l2_pipeline_stats": {"status": "skipped"},
        "background_pending": {"status": "skipped"},
    }


def test_replay_script_applies_qa_limit_to_manifest_and_progress(tmp_path) -> None:
    service = FakeReplayService()
    progress_events: list[dict[str, object]] = []

    artifacts = asyncio.run(
        replay_locomo_samples(
            samples=[_build_sample()],
            eval_service=service,
            run_id="run-1",
            output_root=tmp_path,
            qa_limit=0,
            finalize=False,
            wait_for_background=False,
            progress_reporter=lambda progress: progress_events.append(asdict(progress)),
        )
    )

    assert progress_events[0]["qa_count"] == 0
    assert read_jsonl(artifacts.manifest_path)[0]["qa_count"] == 0
    assert service.write_calls == [("benchmark/locomo/run-1/conv-test", 2)]


def test_parse_args_accepts_skip_finalize_and_background_wait() -> None:
    args = parse_args(
        [
            "--dataset",
            "/tmp/locomo.json",
            "--skip-finalize",
            "--skip-background-wait",
            "--qa-limit",
            "10",
        ]
    )

    assert args.skip_finalize is True
    assert args.skip_background_wait is True
    assert args.qa_limit == 10
