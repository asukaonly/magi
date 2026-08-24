"""Shared skills service access for runtime wiring and API routes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any

from ..config import get_config
from .tool_registry_port import ToolRegistryPort

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SkillsRuntimeBindings:
    skill_indexer: Any
    skill_loader: Any
    skill_runner: Any


def _get_enabled_skill_names() -> set[str]:
    try:
        skills = get_config().tools.skills
        if isinstance(skills, list):
            return {str(skill) for skill in skills}
    except Exception:
        logger.exception("Failed to read enabled skills from runtime config")
    return set()


def get_enabled_skill_names() -> set[str]:
    """Get enabled skill names configured in runtime config."""

    return _get_enabled_skill_names()


def register_enabled_skills(
    skills: dict[str, Any], *, tool_registry: ToolRegistryPort
) -> dict[str, Any]:
    """Register only enabled skills into the shared tool registry."""

    return register_enabled_skills_with_indexer(
        skills=skills, skill_indexer=None, tool_registry=tool_registry
    )


def register_enabled_skills_with_indexer(
    *, skills: dict[str, Any], skill_indexer: Any, tool_registry: ToolRegistryPort
) -> dict[str, Any]:
    """Register only enabled skills into the shared tool registry."""

    enabled_skills = _get_enabled_skill_names()
    filtered_skills = (
        {name: metadata for name, metadata in skills.items() if name in enabled_skills}
        if enabled_skills
        else {}
    )
    if skill_indexer is not None:
        tool_registry.bind_skill_indexer(skill_indexer)
    tool_registry.register_skill_index(filtered_skills)
    logger.info(
        "Registered enabled skills into tool registry | indexed=%s enabled=%s registered=%s",
        len(skills),
        len(enabled_skills),
        len(filtered_skills),
    )
    return filtered_skills


def build_skills_runtime(
    llm_adapter=None,
    permission_gateway_provider=None,
    active_model_provider=None,
    scenario_llm_pool=None,
    *,
    tool_registry: ToolRegistryPort,
    orchestrator_factory=None,
    agent_run_request_factory=None,
) -> SkillsRuntimeBindings:
    """Build shared skills runtime services without storing module-level globals.

    ``orchestrator_factory`` / ``agent_run_request_factory`` are injected by the
    composition root and threaded to the skill sub-agent so the skills layer
    does not import the agent execution engine.
    """

    from .runner import SkillRunner
    from .indexer import SkillIndexer
    from .loader import SkillLoader

    skill_indexer = SkillIndexer()
    skill_loader = SkillLoader(skill_indexer)
    skill_runner = SkillRunner(
        skill_loader,
        llm_adapter,
        permission_gateway_provider=permission_gateway_provider,
        tool_registry=tool_registry,
        orchestrator_factory=orchestrator_factory,
        agent_run_request_factory=agent_run_request_factory,
        active_model_provider=active_model_provider,
        scenario_llm_pool=scenario_llm_pool,
    )

    skills = skill_indexer.scan_all()
    registered_skills = register_enabled_skills_with_indexer(
        skills=skills, skill_indexer=skill_indexer, tool_registry=tool_registry
    )
    logger.info(
        "Skills module initialized | indexed=%s registered=%s",
        len(skills),
        len(registered_skills),
    )
    return SkillsRuntimeBindings(
        skill_indexer=skill_indexer,
        skill_loader=skill_loader,
        skill_runner=skill_runner,
    )
