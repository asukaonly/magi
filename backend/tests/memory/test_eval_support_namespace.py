"""Tests for eval namespace helpers."""

from __future__ import annotations

import pytest

from magi.memory.eval_support.namespace import (
    EvalNamespaceManager,
    build_eval_namespace,
    sanitize_eval_namespace_component,
)


def test_build_eval_namespace_is_deterministic() -> None:
    namespace = build_eval_namespace(
        benchmark_name="LongMemEval",
        run_id="run 01",
        question_id="question/1",
    )

    assert namespace == "benchmark/longmemeval/run_01/question_1"


def test_sanitize_eval_namespace_component_removes_unsafe_chars() -> None:
    assert sanitize_eval_namespace_component(" LongMemEval / Run:01 ") == "longmemeval_run_01"


@pytest.mark.asyncio
async def test_namespace_reset_only_targets_requested_namespace() -> None:
    cleaned: list[str] = []

    async def _clean(namespace: str) -> int:
        cleaned.append(namespace)
        return 3

    manager = EvalNamespaceManager(cleaner=_clean)
    ns_one = manager.create_namespace(
        benchmark_name="longmemeval",
        run_id="run-a",
        question_id="q1",
    )
    ns_two = manager.create_namespace(
        benchmark_name="longmemeval",
        run_id="run-a",
        question_id="q2",
    )

    removed = await manager.reset_namespace(ns_one)

    assert removed == 3
    assert cleaned == [ns_one]
    assert manager.is_registered(ns_one) is False
    assert manager.is_registered(ns_two) is True
