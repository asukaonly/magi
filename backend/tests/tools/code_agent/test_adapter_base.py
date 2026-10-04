"""Tests for the adapter base contract and stream parser."""
from __future__ import annotations

import pytest

from magi.tools.code_agent.adapters.base import (
    CancelToken,
)
from magi.tools.code_agent.adapters._stream_parser import parse_jsonl_lines


def test_cancel_token_starts_uncancelled():
    tok = CancelToken()
    assert not tok.cancelled


def test_cancel_token_cancel_is_idempotent():
    tok = CancelToken()
    tok.cancel()
    tok.cancel()
    assert tok.cancelled


@pytest.mark.parametrize(
    "case_input_bytes",
    [
        pytest.param(b'{"a":1}\n{"b":2}\n', id="parse_jsonl_lines_returns_dicts_per_line"),
        pytest.param(
            b'\n{"a":1}\nnot-json\n  \n{"b":2}\n', id="parse_jsonl_lines_skips_blank_and_invalid"
        ),
    ],
)
def test_jsonl_parser_keeps_valid_objects_amid_invalid_lines(case_input_bytes):
    raw = case_input_bytes
    parsed = list(parse_jsonl_lines(raw))
    assert parsed == [{"a": 1}, {"b": 2}]
