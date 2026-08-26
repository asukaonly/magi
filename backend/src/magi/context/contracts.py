"""Contracts for prompt-context ownership within the context layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(slots=True)
class ContextPolicyDecision:
    """Decision describing how implicit prompt context should be gathered."""

    retrieve_implicit_memory: bool
    retrieval_query: Optional[str]
    allowed_layers: tuple[str, ...] = ("L0",)


@dataclass(slots=True)
class PromptPackage:
    """Fully assembled prompt artifacts consumed by task-agent handlers."""

    prompt_context: Any
    system_prompt: str
    runtime_world_state: str = ""
    working_context: str = ""
    recent_tool_errors_block: str = ""
    memory_availability: str = "unknown"
    memory_retrieval_status: str = "unknown"
