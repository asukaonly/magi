"""Schemas for modular LLM prompt context assembly."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..personality.turn_planner import PersonaTurnPlan


@dataclass
class IdentityConstraintContext:
    """Module 1: System identity and behavior constraints."""

    system_definition: str
    core_truths_and_boundaries: str


@dataclass
class RetrievalMemoryContext:
    """Retrieved memory payload for Module 2."""

    l0_workbench: List[Dict[str, Any]] = field(default_factory=list)
    l2_entity_cards: List[Dict[str, Any]] = field(default_factory=list)
    l3_reflection_memory: List[Dict[str, Any]] = field(default_factory=list)
    l4_procedural_memory: List[Dict[str, Any]] = field(default_factory=list)
    preference_memory: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SelfMemoryContext:
    """Module 2: Agent self-memory from agent perspective."""

    persona_turn_plan: Optional[PersonaTurnPlan] = None
    retrieval_memory: RetrievalMemoryContext = field(default_factory=RetrievalMemoryContext)
    persona_journal_entries: List[Dict[str, Any]] = field(default_factory=list)  # Recent persona reflections


@dataclass
class ProfileMemoryContext:
    """Module 3: User profile memory."""

    user_id: str = ""
    user_name: str = ""
    user_preferences: Dict[str, Any] = field(default_factory=dict)
    prompt_summary: List[str] = field(default_factory=list)
    recent_emotion: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RuntimeSystemContext:
    """Module 4: Runtime system metadata."""

    current_date: str
    timezone: str
    os_name: str
    os_version: str
    cwd: str
    agent_id: str
    agent_type: str
    active_attachments: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ToolCatalogContext:
    """Module 5: Turn-level tool availability signal."""

    selected_tools: List[str] = field(default_factory=list)


@dataclass
class PromptAssemblyContext:
    """Top-level context object for prompt rendering."""

    identity_constraints: IdentityConstraintContext
    self_memory: SelfMemoryContext
    profile_memory: ProfileMemoryContext
    runtime_system: RuntimeSystemContext
    tool_catalog: ToolCatalogContext
    metadata: Dict[str, Any] = field(default_factory=dict)
