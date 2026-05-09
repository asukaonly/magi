"""Reasoning / thinking parameter dialect table.

Different model vendors express the "how much reasoning to spend" knob
in incompatible payload shapes:

- OpenAI / DeepSeek / OpenAI-compatible gateways use
  ``reasoning_effort: "low" | "medium" | "high"`` as a top-level kwarg.
- Anthropic uses ``thinking: {type: "enabled", budget_tokens: N}`` as a
  top-level kwarg with provider-specific token budgets per depth.
- Alibaba DashScope / Bailian (vendor=DASHSCOPE) uses
  ``extra_body.enable_thinking: bool``.
- Zhipu GLM (vendor=GLM) uses ``extra_body.thinking: {type: "disabled"}``
  and only supports an on/off toggle.
- Grok / Gemini / Kimi / MiniMax (vendor=GROK / GENERIC) currently expose
  no public reasoning/thinking knob; they map to ``NONE``.

Historically the dialect was looked up by ``provider_name``. That broke
on OneAPI / NewAPI gateways where a single ``provider`` entry proxies
models from multiple vendors (``glm-4-plus`` + ``qwen-max`` + ``claude-*``
under one URL): provider was no longer the right key. Dialect is now
keyed off ``ModelVendor`` declared on the model itself, so the lookup
is correct regardless of who hosts the endpoint.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable, Dict

from ..config.models import ModelVendor, ThinkingDepth


class ReasoningDialect(str, Enum):
    """How a vendor expresses LLM reasoning/thinking control."""

    NONE = "none"
    OPENAI_EFFORT = "openai_effort"
    ANTHROPIC_BUDGET = "anthropic_budget"
    DASHSCOPE_ENABLE = "dashscope_enable"
    GLM_TOGGLE = "glm_toggle"


# vendor → dialect. ``GENERIC`` and ``GROK`` map to ``NONE`` because
# neither has a public reasoning-control payload at the moment; if they
# add one in the future, add the dialect here without touching call
# sites. DeepSeek is intentionally not its own vendor — its hosted API is
# OpenAI-compatible and uses ``reasoning_effort``, so ``ModelVendor.OPENAI``
# is the correct classification.
_VENDOR_TO_DIALECT: Dict[ModelVendor, "ReasoningDialect"] = {
    ModelVendor.OPENAI: ReasoningDialect.OPENAI_EFFORT,
    ModelVendor.ANTHROPIC: ReasoningDialect.ANTHROPIC_BUDGET,
    ModelVendor.DASHSCOPE: ReasoningDialect.DASHSCOPE_ENABLE,
    ModelVendor.GLM: ReasoningDialect.GLM_TOGGLE,
    ModelVendor.GROK: ReasoningDialect.NONE,
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
    mapping = {
        ThinkingDepth.NONE: "none",
        ThinkingDepth.LOW: "low",
        ThinkingDepth.MEDIUM: "medium",
        ThinkingDepth.HIGH: "high",
        ThinkingDepth.MAX: "high",
    }
    return {"_kwargs": {"reasoning_effort": mapping.get(depth, "medium")}}


def _anthropic_budget_builder(depth: ThinkingDepth) -> Dict[str, Any]:
    # Anthropic exposes "extended thinking" via a token budget. Empirical
    # values from Anthropic's docs / our smoke tests; bumping these
    # affects per-call cost. If you tune them, mirror updates here so the
    # dialect stays the single source of truth.
    budget_map = {
        ThinkingDepth.NONE: None,
        ThinkingDepth.LOW: 2048,
        ThinkingDepth.MEDIUM: 8192,
        ThinkingDepth.HIGH: 16384,
        ThinkingDepth.MAX: 32768,
    }
    tokens = budget_map.get(depth)
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
    "ReasoningDialect",
    "build_reasoning_payload",
    "merge_payload",
    "resolve_dialect",
]
