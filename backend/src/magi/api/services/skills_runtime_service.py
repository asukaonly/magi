"""Explicit API services for shared skills runtime access."""

from __future__ import annotations

from dependency_injector import providers

from ...core.container import get_container
from ...core.runtime_bindings import (
    require_skill_executor,
    require_skill_indexer,
    require_skill_loader,
)
from ...skills.service_access import (
    ensure_skill_indexer as _ensure_skill_indexer,
    get_enabled_skill_names,
    get_skill_executor,
    get_skill_indexer,
    get_skill_loader,
    init_skills_module as _init_skills_module,
    register_enabled_skills,
)


def _bind_initialized_skills() -> None:
    """Expose initialized shared skills services through the DI container."""

    container = get_container()

    skill_indexer = get_skill_indexer()
    if skill_indexer is not None:
        container.skill_indexer.override(providers.Object(skill_indexer))

    skill_loader = get_skill_loader()
    if skill_loader is not None:
        container.skill_loader.override(providers.Object(skill_loader))

    skill_executor = get_skill_executor()
    if skill_executor is not None:
        container.skill_executor.override(providers.Object(skill_executor))


def init_skills_module(llm_adapter=None) -> None:
    """Initialize the shared skills runtime and bind it for API access."""

    _init_skills_module(llm_adapter=llm_adapter)
    _bind_initialized_skills()


def ensure_skill_indexer():
    """Ensure the shared skill indexer exists and bind it for API access."""

    skill_indexer = _ensure_skill_indexer()
    get_container().skill_indexer.override(providers.Object(skill_indexer))
    return skill_indexer

__all__ = [
    "ensure_skill_indexer",
    "get_enabled_skill_names",
    "init_skills_module",
    "register_enabled_skills",
    "require_skill_executor",
    "require_skill_indexer",
    "require_skill_loader",
]
