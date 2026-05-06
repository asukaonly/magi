"""Tests for the adapter base contract and stream parser."""
from __future__ import annotations

from magi.tools.code_agent.adapters.base import (
    AdapterRunOutcome,
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


def test_adapter_run_outcome_default_fields():
    outcome = AdapterRunOutcome(
        exit_code=0, summary="ok", cost=None, error=None,
    )
    assert outcome.exit_code == 0
    assert outcome.summary == "ok"
    assert outcome.cost is None
    assert outcome.error is None


def test_parse_jsonl_lines_returns_dicts_per_line():
    raw = b'{"a":1}\n{"b":2}\n'
    parsed = list(parse_jsonl_lines(raw))
    assert parsed == [{"a": 1}, {"b": 2}]


def test_parse_jsonl_lines_skips_blank_and_invalid():
    raw = b'\n{"a":1}\nnot-json\n  \n{"b":2}\n'
    parsed = list(parse_jsonl_lines(raw))
    assert parsed == [{"a": 1}, {"b": 2}]
