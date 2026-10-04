"""Tests for eval namespace helpers."""

from __future__ import annotations

import pytest

from magi.memory.eval_support.namespace import (
    build_eval_namespace,
)


@pytest.mark.parametrize(
    "parts,expected",
    [
        (("LongMemEval", "run 01", "question/1"), "benchmark/longmemeval/run_01/question_1"),
        ((" LongMemEval / Run:01 ", "", "..."), "benchmark/longmemeval_run_01/unknown/unknown"),
        (("BENCH", "r-1.2", "a___b"), "benchmark/bench/r-1.2/a_b"),
    ],
)
def test_namespace_normalizes_each_component(parts, expected):
    assert (
        build_eval_namespace(benchmark_name=parts[0], run_id=parts[1], question_id=parts[2])
        == expected
    )
