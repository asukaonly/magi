"""Stable system-prompt contracts shared by every unified agent driver."""

from __future__ import annotations

from ..config.constants import SYSTEM_PROMPT_CACHE_BOUNDARY


DEFAULT_HEADLESS_SYSTEM_PROMPT = "\n".join(
    (
        "You are executing a bounded task through the unified agent runtime.",
        "Follow the assigned objective, runtime-provided context, capability and "
        "permission boundaries, and observed evidence. Use exposed tools when they "
        "materially improve correctness; otherwise answer directly.",
        "Do not fabricate tool results or claim unverified completion.",
        SYSTEM_PROMPT_CACHE_BOUNDARY,
    )
)


def require_stable_system_prompt(system_prompt: str) -> str:
    """Validate and normalize one stable system-prompt epoch."""

    normalized = str(system_prompt or "").strip()
    boundary_count = normalized.count(SYSTEM_PROMPT_CACHE_BOUNDARY)
    if boundary_count != 1:
        raise ValueError("Stable system prompt must contain exactly one cache boundary")
    if not normalized.endswith(SYSTEM_PROMPT_CACHE_BOUNDARY):
        raise ValueError("Stable system prompt must end at the cache boundary")
    return normalized


def resolve_headless_system_prompt(system_prompt: str | None) -> str:
    """Return the stable explicit prompt or the canonical headless default."""

    return require_stable_system_prompt(
        system_prompt if str(system_prompt or "").strip() else DEFAULT_HEADLESS_SYSTEM_PROMPT
    )


__all__ = [
    "DEFAULT_HEADLESS_SYSTEM_PROMPT",
    "require_stable_system_prompt",
    "resolve_headless_system_prompt",
]
