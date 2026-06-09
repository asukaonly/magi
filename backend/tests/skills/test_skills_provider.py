from __future__ import annotations

import pytest
from dependency_injector import providers

from magi.core.container import get_container
from magi.skills.provider import resolve_skill_indexer


def test_resolve_skill_indexer_raises_when_unbound() -> None:
    with pytest.raises(RuntimeError, match="skill_indexer"):
        resolve_skill_indexer()


def test_resolve_skill_indexer_returns_bound_object() -> None:
    container = get_container()
    token = object()
    container.skill_indexer.override(providers.Object(token))
    try:
        assert resolve_skill_indexer() is token
    finally:
        container.skill_indexer.reset_override()
