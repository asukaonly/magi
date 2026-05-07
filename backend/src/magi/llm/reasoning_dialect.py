"""Reasoning / thinking parameter dialect table.

Different providers express the "how much reasoning to spend" knob in
incompatible payload shapes:

- OpenAI / Grok / DeepSeek / local OpenAI-compatible gateways use
  ``reasoning_effort: "low" | "medium" | "high"`` as a top-level kwarg.
- Anthropic uses ``thinking: {type: "enabled", budget_tokens: N}`` as a
  top-level kwarg with provider-specific token budgets per depth.
- Alibaba DashScope / Bailian uses ``extra_body.enable_thinking: bool``.
- Zhipu GLM uses ``extra_body.thinking: {type: "disabled"}`` and only
  supports an on/off toggle; everything except ``NONE`` keeps the
  default-on behavior.
- Some providers (Gemini, Kimi, MiniMax, …) currently expose no public
  reasoning/thinking knob at all. They map to ``none``.

Historically these branches lived as a hand-rolled ``if provider == ...``
chain in ``provider_bridge/options.py`` whose comments admitted things
like "DashScope/Bailian must precede GLM" and ``provider != "grok"`` —
both classic whack-a-mole rule-table smells. This module replaces that
chain with a small enum + builder table so adding a new provider is a
data-only change and order is no longer significant.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable, Dict

from ..config.models import ThinkingDepth


class ReasoningDialect(str, Enum):
    """How a provider expresses LLM reasoning/thinking control."""

    NONE = "none"
    OPENAI_EFFORT = "openai_effort"
    ANTHROPIC_BUDGET = "anthropic_budget"
    DASHSCOPE_ENABLE = "dashscope_enable"
    GLM_TOGGLE = "glm_toggle"


# Default dialect per known provider. ``CUSTOM`` is intentionally absent —
# custom providers fall back via the OpenAI-compatible runtime detection
# in ``ScenarioLLMPool``, which already returns one of the names below.
DEFAULT_PROVIDER_DIALECTS: Dict[str, ReasoningDialect] = {
    "openai": ReasoningDialect.OPENAI_EFFORT,
    "grok": ReasoningDialect.NONE,  # grok currently has no public effort knob
    "deepseek": ReasoningDialect.OPENAI_EFFORT,
    "local": ReasoningDialect.OPENAI_EFFORT,
    "anthropic": ReasoningDialect.ANTHROPIC_BUDGET,
    "dashscope": ReasoningDialect.DASHSCOPE_ENABLE,
    "glm": ReasoningDialect.GLM_TOGGLE,
    "glm_codeplan": ReasoningDialect.GLM_TOGGLE,
    "gemini": ReasoningDialect.NONE,
    "kimi": ReasoningDialect.NONE,
    "minimax": ReasoningDialect.NONE,
}


def resolve_dialect(provider_name: str) -> ReasoningDialect:
    """Look up the reasoning dialect for ``provider_name``.

    Unknown providers default to ``NONE`` rather than guessing — this is
    safer than the previous behaviour where unmatched providers silently
    received OpenAI ``reasoning_effort``.
    """
    return DEFAULT_PROVIDER_DIALECTS.get(
        str(provider_name or "").strip().lower(), ReasoningDialect.NONE
    )


# ---------------------------------------------------------------------------
# Builders
#
# Each builder takes a ThinkingDepth and returns a dict that is merged into
# the LLM call kwargs. Builders return either:
#   {"_kwargs": {...}}     to spread top-level kwargs (Anthropic, OpenAI)
#   {"_extra_body": {...}} to spread into extra_body (DashScope, GLM)
# This wrapper indirection keeps the apply step trivial and the builders
# pure / unit-testable.
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
    # Default-on; GLM has no positive toggle, so we leave the request
    # untouched for any non-NONE depth.
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

    - ``_kwargs``      → merge-into top-level call kwargs
    - ``_extra_body``  → merge-into the ``extra_body`` sub-dict

    Either may be missing or empty if the dialect / depth combination
    requires no parameters.
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
    "DEFAULT_PROVIDER_DIALECTS",
    "ReasoningDialect",
    "build_reasoning_payload",
    "merge_payload",
    "resolve_dialect",
]
