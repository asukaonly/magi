"""Reasoning controls must reach each vendor's outgoing request payload."""

from copy import deepcopy

import pytest

from magi.config.models import ModelVendor, ThinkingDepth
from magi.llm.reasoning_dialect import (
    _VENDOR_TO_DIALECT,
    anthropic_thinking_is_adaptive_only,
    build_reasoning_payload,
    merge_payload,
    resolve_dialect,
)

_OPENAI_PAYLOADS = (
    {},
    {"reasoning_effort": "low"},
    {"reasoning_effort": "medium"},
    {"reasoning_effort": "high"},
    {"reasoning_effort": "high"},
)
_TOGGLE_PAYLOADS = ({"extra_body": {"thinking": {"type": "disabled"}}}, {}, {}, {}, {})
_VENDOR_PAYLOADS = [
    (ModelVendor.OPENAI, _OPENAI_PAYLOADS),
    (ModelVendor.GROK, _OPENAI_PAYLOADS),
    (ModelVendor.GEMINI, _OPENAI_PAYLOADS),
    (ModelVendor.GLM, _TOGGLE_PAYLOADS),
    (ModelVendor.KIMI, _TOGGLE_PAYLOADS),
    (ModelVendor.MINIMAX, _TOGGLE_PAYLOADS),
    (
        ModelVendor.ANTHROPIC,
        (
            {},
            {"thinking": {"type": "enabled", "budget_tokens": 2048}},
            {"thinking": {"type": "enabled", "budget_tokens": 8192}},
            {"thinking": {"type": "enabled", "budget_tokens": 16384}},
            {"thinking": {"type": "enabled", "budget_tokens": 32768}},
        ),
    ),
    (
        ModelVendor.DEEPSEEK,
        (
            {"extra_body": {"thinking": {"type": "disabled"}}},
            {"reasoning_effort": "high", "extra_body": {"thinking": {"type": "enabled"}}},
            {"reasoning_effort": "high", "extra_body": {"thinking": {"type": "enabled"}}},
            {"reasoning_effort": "high", "extra_body": {"thinking": {"type": "enabled"}}},
            {"reasoning_effort": "max", "extra_body": {"thinking": {"type": "enabled"}}},
        ),
    ),
    (
        ModelVendor.DASHSCOPE,
        (
            {"extra_body": {"enable_thinking": False}},
            {"extra_body": {"enable_thinking": True}},
            {"extra_body": {"enable_thinking": True}},
            {"extra_body": {"enable_thinking": True}},
            {"extra_body": {"enable_thinking": True}},
        ),
    ),
    (ModelVendor.GENERIC, ({}, {}, {}, {}, {})),
    (None, ({}, {}, {}, {}, {})),
]


def test_vendor_contract_covers_every_declared_vendor():
    assert {vendor for vendor, _ in _VENDOR_PAYLOADS if vendor is not None} == set(ModelVendor)
    assert set(_VENDOR_TO_DIALECT) == set(ModelVendor)


@pytest.mark.parametrize(
    "vendor,expected_payloads",
    _VENDOR_PAYLOADS,
    ids=lambda value: value.value if isinstance(value, ModelVendor) else None,
)
@pytest.mark.parametrize(
    "depth,position",
    [
        (ThinkingDepth.NONE, 0),
        (ThinkingDepth.LOW, 1),
        (ThinkingDepth.MEDIUM, 2),
        (ThinkingDepth.HIGH, 3),
        (ThinkingDepth.MAX, 4),
    ],
)
def test_vendor_and_depth_produce_exact_outgoing_payload(
    vendor, expected_payloads, depth, position
):
    payload = build_reasoning_payload(resolve_dialect(vendor), depth)
    kwargs = {"model": "resolved-model", "messages": [{"role": "user", "content": "hello"}]}
    merged = merge_payload(kwargs, payload)
    assert merged is kwargs
    assert merged == {
        "model": "resolved-model",
        "messages": [{"role": "user", "content": "hello"}],
        **expected_payloads[position],
    }


@pytest.mark.parametrize(
    "model_id,expected",
    [
        ("claude-opus-4-7", True),
        ("claude-opus-4-8", True),
        ("claude-opus-4-8[1m]", True),
        ("claude-fable-5", True),
        ("Claude-Fable-5-Preview", True),
        ("claude-opus-4-6", False),
        ("claude-sonnet-4-6", False),
        ("claude-haiku-4-5", False),
        ("claude-opus-4-0", False),
        ("", False),
        ("some-other-model", False),
    ],
)
def test_adaptive_thinking_classification(model_id, expected):
    assert anthropic_thinking_is_adaptive_only(model_id) is expected


@pytest.mark.parametrize(
    "initial,payload,expected",
    [
        (
            {"existing": "value", "reasoning_effort": "low"},
            {"_kwargs": {"reasoning_effort": "high"}},
            {"existing": "value", "reasoning_effort": "high"},
        ),
        (
            {"extra_body": {"foo": 1, "enable_thinking": False}},
            {"_extra_body": {"enable_thinking": True}},
            {"extra_body": {"foo": 1, "enable_thinking": True}},
        ),
        (
            {"existing": "value", "extra_body": {"foo": 1}},
            {"_kwargs": {"top": 1}, "_extra_body": {"nested": 2}},
            {"existing": "value", "top": 1, "extra_body": {"foo": 1, "nested": 2}},
        ),
        ({"a": 1, "extra_body": {"foo": 1}}, {}, {"a": 1, "extra_body": {"foo": 1}}),
    ],
    ids=["kwargs-overwrite", "body-overwrite", "both-preserve-unrelated", "empty-identity"],
)
def test_merge_preserves_unrelated_options_and_applies_overrides(initial, payload, expected):
    kwargs = deepcopy(initial)
    payload_before = deepcopy(payload)
    merged = merge_payload(kwargs, payload)
    assert merged is kwargs
    assert merged == expected
    assert payload == payload_before
