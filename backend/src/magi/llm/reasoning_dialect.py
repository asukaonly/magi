"""Reasoning / thinking parameter dialect table.

Different model vendors express the "how much reasoning to spend" knob
in incompatible payload shapes:

- OpenAI / OpenAI-compatible gateways use
    ``reasoning_effort`` as a top-level kwarg when reasoning is enabled.
- DeepSeek uses ``extra_body.thinking: {type: "enabled"|"disabled"}``
    plus top-level ``reasoning_effort: "high" | "max"`` when thinking is
    enabled.
- Anthropic uses ``thinking: {type: "enabled", budget_tokens: N}`` as a
  top-level kwarg with provider-specific token budgets per depth.
- Alibaba DashScope / Bailian (vendor=DASHSCOPE) uses
  ``extra_body.enable_thinking: bool``.
- Zhipu GLM (vendor=GLM) uses ``extra_body.thinking: {type: "disabled"}``
  and only supports an on/off toggle.
- Grok (vendor=GROK) and Gemini (vendor=GEMINI) both expose a top-level
  ``reasoning_effort`` on their OpenAI-compatible endpoints, so they map
  to ``OPENAI_EFFORT`` (the builder omits the kwarg on NONE, which is
  safe for models that cannot disable thinking).
- Kimi (vendor=KIMI, Moonshot) and MiniMax (vendor=MINIMAX) use the
  ``extra_body.thinking: {type: ...}`` toggle shape; they map to
  ``GLM_TOGGLE``, which sends ``{type: "disabled"}`` on NONE and nothing
  otherwise — matching their default-on behavior (a no-op on the
  always-on variants).
- Anything with no verified reasoning contract (vendor=GENERIC) maps to
  ``NONE`` and gets no injected reasoning parameters.

Historically the dialect was looked up by ``provider_name``. That broke
on OneAPI / NewAPI gateways where a single ``provider`` entry proxies
models from multiple vendors (``glm-4-plus`` + ``qwen-max`` + ``claude-*``
under one URL): provider was no longer the right key. Dialect is now
keyed off ``ModelVendor`` declared on the model itself, so the lookup
is correct regardless of who hosts the endpoint.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Callable, Dict, Optional

from ..config.models import ModelVendor, ThinkingDepth


class ReasoningDialect(str, Enum):
    """How a vendor expresses LLM reasoning/thinking control."""

    NONE = "none"
    OPENAI_EFFORT = "openai_effort"
    DEEPSEEK_THINKING = "deepseek_thinking"
    ANTHROPIC_BUDGET = "anthropic_budget"
    DASHSCOPE_ENABLE = "dashscope_enable"
    GLM_TOGGLE = "glm_toggle"


# vendor → dialect. Only ``GENERIC`` maps to ``NONE`` (no verified
# reasoning-control payload). Grok and Gemini expose a top-level
# ``reasoning_effort`` on their OpenAI-compatible endpoints; Kimi and
# MiniMax use the ``extra_body.thinking`` toggle. DeepSeek is its own
# vendor because although its transport is OpenAI-compatible, its
# thinking mode also requires ``extra_body.thinking`` toggles.
_VENDOR_TO_DIALECT: Dict[ModelVendor, "ReasoningDialect"] = {
    ModelVendor.OPENAI: ReasoningDialect.OPENAI_EFFORT,
    ModelVendor.DEEPSEEK: ReasoningDialect.DEEPSEEK_THINKING,
    ModelVendor.ANTHROPIC: ReasoningDialect.ANTHROPIC_BUDGET,
    ModelVendor.DASHSCOPE: ReasoningDialect.DASHSCOPE_ENABLE,
    ModelVendor.GLM: ReasoningDialect.GLM_TOGGLE,
    ModelVendor.GROK: ReasoningDialect.OPENAI_EFFORT,
    ModelVendor.GEMINI: ReasoningDialect.OPENAI_EFFORT,
    ModelVendor.KIMI: ReasoningDialect.GLM_TOGGLE,
    ModelVendor.MINIMAX: ReasoningDialect.GLM_TOGGLE,
    ModelVendor.GENERIC: ReasoningDialect.NONE,
}


def resolve_dialect(vendor: ModelVendor | None) -> ReasoningDialect:
    """Look up the reasoning dialect for ``vendor``.

    Unknown / missing vendors map to ``NONE`` rather than guessing a
    provider — the safer default. Calling code is expected to pass the
    vendor declared on the resolved model meta; if that's missing, the
    caller should leave reasoning alone rather than inject parameters
    blindly.
    """
    if vendor is None:
        return ReasoningDialect.NONE
    return _VENDOR_TO_DIALECT.get(vendor, ReasoningDialect.NONE)


# ---------------------------------------------------------------------------
# Builders
#
# Each builder takes a ThinkingDepth and returns a dict that is merged into
# the LLM call kwargs. Builders return either:
#   {"_kwargs": {...}}     to spread top-level kwargs (Anthropic, OpenAI)
#   {"_extra_body": {...}} to spread into extra_body (DashScope, GLM)
# ---------------------------------------------------------------------------


def _none_builder(_depth: ThinkingDepth) -> Dict[str, Any]:
    return {}


def _openai_effort_builder(depth: ThinkingDepth) -> Dict[str, Any]:
    if depth == ThinkingDepth.NONE:
        return {}

    mapping = {
        ThinkingDepth.LOW: "low",
        ThinkingDepth.MEDIUM: "medium",
        ThinkingDepth.HIGH: "high",
        ThinkingDepth.MAX: "high",
    }
    return {"_kwargs": {"reasoning_effort": mapping.get(depth, "medium")}}


def _deepseek_thinking_builder(depth: ThinkingDepth) -> Dict[str, Any]:
    if depth == ThinkingDepth.NONE:
        return {"_extra_body": {"thinking": {"type": "disabled"}}}

    effort_map = {
        ThinkingDepth.LOW: "high",
        ThinkingDepth.MEDIUM: "high",
        ThinkingDepth.HIGH: "high",
        ThinkingDepth.MAX: "max",
    }
    return {
        "_kwargs": {"reasoning_effort": effort_map.get(depth, "high")},
        "_extra_body": {"thinking": {"type": "enabled"}},
    }


# Anthropic exposes budgeted "extended thinking" via a token budget per
# depth. Single source of truth: both ``_anthropic_budget_builder`` and the
# provider-bridge options path read this map, so tuning a value (which
# affects per-call cost) only needs one edit. ``NONE`` maps to ``None``
# meaning "no thinking".
ANTHROPIC_THINKING_BUDGETS: Dict[ThinkingDepth, Optional[int]] = {
    ThinkingDepth.NONE: None,
    ThinkingDepth.LOW: 2048,
    ThinkingDepth.MEDIUM: 8192,
    ThinkingDepth.HIGH: 16384,
    ThinkingDepth.MAX: 32768,
}


def anthropic_thinking_is_adaptive_only(model_id: str) -> bool:
    """Return True when an Anthropic model only supports *adaptive* thinking.

    Adaptive-only models (Opus 4.7+, Fable 5) reject ``budget_tokens`` and
    any sampling params (``temperature``/``top_p``/``top_k``) when thinking
    is on; they must use ``thinking: {type: "adaptive"}`` instead. Shipped
    budgeted models (Opus 4.6, Sonnet 4.6, Haiku 4.5) return False.

    Heuristic, biased toward budgeted (returns False) when the id is
    unrecognized — that path still works on every current model.
    """
    m = (model_id or "").lower()
    if "fable" in m:
        return True
    match = re.search(r"opus-4-(\d+)", m)
    return bool(match and int(match.group(1)) >= 7)


def _anthropic_budget_builder(depth: ThinkingDepth) -> Dict[str, Any]:
    tokens = ANTHROPIC_THINKING_BUDGETS.get(depth)
    if tokens is None:
        return {}
    return {"_kwargs": {"thinking": {"type": "enabled", "budget_tokens": tokens}}}


def _dashscope_enable_builder(depth: ThinkingDepth) -> Dict[str, Any]:
    return {"_extra_body": {"enable_thinking": depth != ThinkingDepth.NONE}}


def _glm_toggle_builder(depth: ThinkingDepth) -> Dict[str, Any]:
    if depth == ThinkingDepth.NONE:
        return {"_extra_body": {"thinking": {"type": "disabled"}}}
    return {}


_BUILDERS: Dict[ReasoningDialect, Callable[[ThinkingDepth], Dict[str, Any]]] = {
    ReasoningDialect.NONE: _none_builder,
    ReasoningDialect.OPENAI_EFFORT: _openai_effort_builder,
    ReasoningDialect.DEEPSEEK_THINKING: _deepseek_thinking_builder,
    ReasoningDialect.ANTHROPIC_BUDGET: _anthropic_budget_builder,
    ReasoningDialect.DASHSCOPE_ENABLE: _dashscope_enable_builder,
    ReasoningDialect.GLM_TOGGLE: _glm_toggle_builder,
}


def build_reasoning_payload(
    dialect: ReasoningDialect, depth: ThinkingDepth
) -> Dict[str, Any]:
    """Return the dialect-specific payload fragment.

    The returned dict has at most two keys:
    - ``_kwargs``      → merge into top-level call kwargs
    - ``_extra_body``  → merge into the ``extra_body`` sub-dict
    """
    builder = _BUILDERS.get(dialect, _none_builder)
    return builder(depth)


def merge_payload(kwargs: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    """Apply a dialect payload to an existing call-kwargs dict in place-like fashion."""
    extra_body_patch = payload.get("_extra_body")
    if extra_body_patch:
        existing = kwargs.get("extra_body", {})
        kwargs["extra_body"] = {**existing, **extra_body_patch}
    kwargs_patch = payload.get("_kwargs")
    if kwargs_patch:
        kwargs.update(kwargs_patch)
    return kwargs


__all__ = [
    "ANTHROPIC_THINKING_BUDGETS",
    "ReasoningDialect",
    "anthropic_thinking_is_adaptive_only",
    "build_reasoning_payload",
    "merge_payload",
    "resolve_dialect",
]
